"""Build the data for "The 65th birthday that never comes" (medicare-at-65).

Who is uninsured after 65, by where they were born, citizenship, the age they
arrived in the US, years in the US and the language they speak, from the
American Community Survey Public Use Microdata Sample (PUMS).

Inputs (public, no key; downloaded once into _viz/cache/medicare65/):
  ACS 1-year PUMS person files 2022, 2023, 2024
  ACS 2020-2024 5-year PUMS person file
  PUMS data dictionaries (code labels)
Universe: civilian noninstitutional population (RELSHIPP 37, people living in
institutional group quarters, is dropped), the universe ACS uses for health
insurance. Uninsured = HICOV 2.
Standard errors: successive difference replication with the 80 replicate
weights, var = 4/80 * sum (theta_r - theta)^2. The three 1-year files are
pooled by dividing every weight (full and replicate) by 3.

Run: python3 medicare-at-65/scripts/build_data.py   (needs numpy)
The first run streams ~4.6 GB of zipped CSV (about 10-20 minutes on 6 cores);
the extracts are cached as .npz so later runs take seconds.
"""
import array
import csv
import io
import json
import sys
import urllib.request
import zipfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "medicare-at-65" / "data"
CACHE = ROOT / "_viz" / "cache" / "medicare65"
SCOUT = ROOT / "_viz" / "cache" / "scout_pums"  # earlier copies of the same Census files, if present
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "usnish.github.io data viz build (contact via github.com/usnish)"}

PUMS = "https://www2.census.gov/programs-surveys/acs/data/pums/{y}/{kind}/csv_pus.zip"
DICT = "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_{v}.csv"

KEEP = ["AGEP", "NATIVITY", "CIT", "YOEP", "HICOV", "HINS1", "HINS2", "HINS3", "HINS4", "HINS5", "HINS6",
        "HINS7", "ENG", "LANX", "LANP", "POBP", "PINCP", "ADJINC", "POVPIP", "RELSHIPP", "SEX", "PWGTP"] + \
       [f"PWGTP{i}" for i in range(1, 81)]
DERIVED = ["YEAR", "HHEMP"]  # survey year (from SERIALNO); household has an employed member aged 18-64
COLS = KEEP + DERIVED
C = {c: i for i, c in enumerate(COLS)}

# CMS 2026 Medicare premiums (CMS fact sheet, 2026 Medicare Parts A & B premiums and deductibles)
PART_A_UNDER30Q = 565.0
PART_A_30_39Q = 311.0
PART_B_STD = 202.90


def fetch(url, path):
    if not path.exists():
        print("  downloading", url, flush=True)
        tmp = path.with_suffix(".part")
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 22)
                if not b:
                    break
                f.write(b)
        tmp.rename(path)
    return path


def pums_zip(year, kind):
    """Local path to a PUMS person zip, reusing earlier cached copies when present."""
    if kind == "1-Year":
        for p in (SCOUT / f"y{year}" / "csv_pus.zip", CACHE / f"csv_pus_1y{year}.zip"):
            if p.exists():
                return p
        if year == 2024 and (SCOUT / "csv_pus.zip").exists():
            with zipfile.ZipFile(SCOUT / "csv_pus.zip") as z:
                if "ACS2024_PUMS_README.pdf" in z.namelist():
                    return SCOUT / "csv_pus.zip"
        return fetch(PUMS.format(y=year, kind=kind), CACHE / f"csv_pus_1y{year}.zip")
    return fetch(PUMS.format(y=year, kind=kind), CACHE / f"csv_pus_5y{year}.zip")


def extract(task):
    """Stream one CSV member of a PUMS zip and keep people aged >= minage (cached .npz)."""
    zpath, member, minage, tag = task
    out = CACHE / f"ext_{tag}_{member.replace('.csv', '')}.npz"
    if out.exists():
        return out
    data = array.array("i")
    serials = array.array("q")
    emp_hh = set()
    with zipfile.ZipFile(zpath) as z, z.open(member) as raw:
        f = io.TextIOWrapper(raw, encoding="ascii", newline="")
        head = f.readline().rstrip("\r\n").split(",")
        ix = {h: i for i, h in enumerate(head)}
        idx = [ix[c] for c in KEEP]
        iage, iser, iesr = ix["AGEP"], ix["SERIALNO"], ix["ESR"]
        nsplit = max(iage, iesr) + 1
        for line in f:
            p = line.split(",", nsplit)
            age = int(p[iage])
            s = p[iser]
            sid = int(s[:4]) * 10**10 + (10**9 if s[4:6] == "GQ" else 0) + int(s[6:])
            if 18 <= age <= 64 and p[iesr] in ("1", "2", "4", "5"):
                emp_hh.add(sid)
            if age < minage:
                continue
            q = line.rstrip("\r\n").split(",")
            data.extend([int(q[i]) if q[i] else -1 for i in idx])
            data.extend([int(s[:4]), 0])
            serials.append(sid)
    a = np.frombuffer(data, dtype=np.int32).reshape(-1, len(COLS)).copy()
    sid = np.frombuffer(serials, dtype=np.int64)
    a[:, C["HHEMP"]] = np.fromiter((x in emp_hh for x in sid), dtype=np.int32, count=len(sid))
    np.savez(out, a=a)
    print(f"  {tag} {member}: kept {len(a):,}", flush=True)
    return out


def load(tag, zpath, minage):
    with zipfile.ZipFile(zpath) as z:
        members = sorted(m for m in z.namelist() if m.endswith(".csv"))
    return [(str(zpath), m, minage, tag) for m in members]


def dictionary(var, version):
    path = fetch(DICT.format(v=version), CACHE / f"PUMS_Data_Dictionary_{version}.csv")
    lab = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.reader(f):
            if len(r) >= 7 and r[0] == "VAL" and r[1] == var and r[4] == r[5]:
                try:
                    lab[int(r[4])] = r[6]
                except ValueError:
                    pass
    return lab


# Estimation ------------------------------------------------------------------

class Survey:
    def __init__(self, a, scale=1.0):
        a = a[a[:, C["RELSHIPP"]] != 37]  # civilian noninstitutional universe
        self.a = a
        self.W = a[:, C["PWGTP"]:C["PWGTP80"] + 1].astype(np.float32) / np.float32(scale)  # col 0 = full weight
        self.v = lambda c: a[:, C[c]]
        age, yoep, year = self.v("AGEP"), self.v("YOEP"), self.v("YEAR")
        fb = self.v("NATIVITY") == 2
        self.age = age
        self.fb = fb
        self.unins = self.v("HICOV") == 2
        self.yrs = np.where(fb & (yoep > 0), year - yoep, -1)        # years since (most recent) entry
        self.arrage = np.where(fb & (yoep > 0), age - (year - yoep), -1)  # approximate age at arrival
        self.noncit = self.v("CIT") == 5
        self.nat = self.v("CIT") == 4
        self.eng = self.v("ENG")
        self.lep = (self.eng >= 2) & (self.eng <= 4)
        self.engonly = self.v("LANX") == 2

    def cells(self, cell, ncell, y=None):
        """Weighted rate of y (default: uninsured) within each cell id (-1 = skip), with SDR SEs."""
        y = self.unins if y is None else y
        ok = cell >= 0
        c = cell[ok]
        W, yy = self.W[ok], y[ok]
        den = np.stack([np.bincount(c, weights=W[:, r], minlength=ncell) for r in range(81)], 1)
        num = np.stack([np.bincount(c, weights=W[:, r] * yy, minlength=ncell) for r in range(81)], 1)
        n = np.bincount(c, minlength=ncell)
        nun = np.bincount(c, weights=yy.astype(float), minlength=ncell)
        with np.errstate(invalid="ignore", divide="ignore"):
            rate = num / den
        est = rate[:, 0]
        se = np.sqrt(4 / 80 * ((rate[:, 1:] - est[:, None]) ** 2).sum(1))
        return dict(rate=est, se=se, n=n, n_unins=nun.astype(int), pop=den[:, 0], unins=num[:, 0])

    def one(self, mask, y=None):
        r = self.cells(np.where(mask, 0, -1), 1, y)
        return {k: (v[0].item() if hasattr(v[0], "item") else v[0]) for k, v in r.items()}

    def total(self, mask):
        t = self.W[mask].sum(0, dtype=np.float64)
        return t[0], np.sqrt(4 / 80 * ((t[1:] - t[0]) ** 2).sum())


def wmedian(x, w):
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = np.cumsum(w)
    return float(x[np.searchsorted(cw, cw[-1] / 2)])


def pct(x, d=1):
    return None if x is None or not np.isfinite(x) else round(100 * float(x), d)


def ci(rate, se):
    lo = max(0.0, rate - 1.96 * se)
    hi = min(1.0, rate + 1.96 * se)
    return pct(lo, 2), pct(hi, 2)


def main():
    tasks = []
    for y in (2022, 2023, 2024):
        tasks += load(f"1y{y}", pums_zip(y, "1-Year"), 55)
    tasks += load("5y2024", pums_zip(2024, "5-Year"), 65)
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    with Pool(workers) as pool:
        paths = pool.map(extract, tasks, chunksize=1)
    by = {}
    for t, p in zip(tasks, paths):
        by.setdefault(t[3], []).append(np.load(p)["a"])
    one = {k: np.concatenate(v) for k, v in by.items()}

    S24 = Survey(one["1y2024"])
    P = Survey(np.concatenate([one["1y2022"], one["1y2023"], one["1y2024"]]), scale=3.0)
    F = Survey(one["5y2024"])
    summary = {}

    # 1. Composition of the uninsured 65+ (2024 1-year) ------------------------------
    s = S24
    old = s.age >= 65
    tot, tot_se = s.total(old)
    un, un_se = s.total(old & s.unins)
    steps = [
        ("fb", "Born outside the US", s.fb),
        ("noncit", "Not a US citizen", s.noncit),
        ("arr55", "Moved to the US at 55 or older", s.fb & (s.arrage >= 55)),
        ("lep", "Speaks English less than “very well”", s.lep),
    ]
    comp = {"year": 2024, "uninsured_65": round(un), "uninsured_65_moe90": round(1.645 * un_se),
            "pop_65": round(tot), "uninsured_rate_65": pct(un / tot, 2), "steps": []}
    for key, label, m in steps:
        sh_un = s.one(old & s.unins, m.astype(float))  # share of uninsured seniors in group
        sh_all = s.one(old, m.astype(float))
        comp["steps"].append({"key": key, "label": label,
                              "share_uninsured": pct(sh_un["rate"]), "share_uninsured_se": pct(sh_un["se"], 2),
                              "share_all": pct(sh_all["rate"]), "share_all_se": pct(sh_all["se"], 2)})
    notwell = s.one(old & s.unins & s.fb, ((s.eng == 3) | (s.eng == 4)).astype(float))
    comp["fb_uninsured_not_well_or_not_at_all"] = pct(notwell["rate"])
    for key, m in (("usborn", ~s.fb), ("naturalized", s.nat), ("noncitizen", s.noncit), ("all", np.ones_like(old))):
        r = s.one(old & m)
        comp.setdefault("rates", {})[key] = {"rate": pct(r["rate"], 2), "se": pct(r["se"], 3), "n": int(r["n"])}
    (OUT / "composition.json").write_text(json.dumps(comp, indent=1))
    summary["composition"] = comp

    # 2. Single-year-of-age curves by age at arrival (pooled 2022-24) -----------------
    s = P
    ages = np.arange(55, 86)
    groups = [
        ("usborn", "Born in the US", ~s.fb),
        ("arr_lt45", "Moved here before 45", s.fb & (s.arrage >= 0) & (s.arrage < 45)),
        ("arr_45_59", "Moved here at 45–59", s.fb & (s.arrage >= 45) & (s.arrage < 60)),
        ("arr_60p", "Moved here at 60 or older", s.fb & (s.arrage >= 60)),
        ("lep_cit", "Limited English, US citizen", s.lep & ~s.noncit),
        ("lep_noncit", "Limited English, not a citizen", s.lep & s.noncit),
        ("eng_only", "Speaks only English at home", s.engonly),
    ]
    rows = []
    inage = (s.age >= 55) & (s.age <= 85)
    for key, label, m in groups:
        cell = np.where(m & inage, s.age - 55, -1)
        r = s.cells(cell, len(ages))
        for i, a in enumerate(ages):
            ok = r["n"][i] >= 100
            lo, hi = ci(r["rate"][i], r["se"][i]) if ok else (None, None)
            rows.append({"group": key, "label": label, "age": int(a), "n": int(r["n"][i]),
                         "pop": round(r["pop"][i]), "rate": pct(r["rate"][i], 2) if ok else None,
                         "lo": lo, "hi": hi})
    write_csv(OUT / "curves.csv", rows, ["group", "label", "age", "n", "pop", "rate", "lo", "hi"])
    cv = {(r["group"], r["age"]): r["rate"] for r in rows}
    summary["curves_at"] = {g: {a: cv[(g, a)] for a in (60, 62, 64, 65, 66, 70, 75, 80, 85)} for g, _, _ in groups}
    # The 60+ arrivals: change from 64 to 66 vs US-born
    summary["groups"] = {g: l for g, l, _ in groups}

    # 3. Years in the US, people 65+ (pooled 2022-24) ------------------------------
    old = s.age >= 65
    cell = np.where(old & s.fb & (s.yrs >= 0), np.minimum(s.yrs, 31), -1)
    r = s.cells(cell, 32)
    yrows = []
    for y in range(32):
        lo, hi = ci(r["rate"][y], r["se"][y])
        yrows.append({"years": y if y < 31 else "31+", "n": int(r["n"][y]), "pop": round(r["pop"][y]),
                      "uninsured": round(r["unins"][y]), "rate": pct(r["rate"][y], 2), "lo": lo, "hi": hi})
    write_csv(OUT / "years_in_us.csv", yrows, ["years", "n", "pop", "uninsured", "rate", "lo", "hi"])
    # step tests: difference between adjacent years with SE (independent cells approx)
    def step(a, b):
        d = r["rate"][b] - r["rate"][a]
        se = np.sqrt(r["se"][a] ** 2 + r["se"][b] ** 2)
        return {"from": a, "to": b, "diff_pp": pct(d, 1), "z": round(float(d / se), 1)}
    summary["years_steps"] = [step(y, y + 1) for y in range(0, 30)]
    summary["years_rate"] = {y: pct(r["rate"][y], 1) for y in range(0, 31)}
    pooled_fb_old = s.one(old & s.fb)
    summary["fb65_rate_pooled"] = pct(pooled_fb_old["rate"], 1)

    # 4. Who the recently arrived uninsured seniors are (pooled 2022-24) ------------
    rec = old & s.fb & s.unins & (s.yrs >= 0) & (s.yrs < 10)
    w = s.W[:, 0].astype(np.float64)
    adj = s.v("ADJINC") / 1e6
    pinc = s.v("PINCP") * adj
    pov = s.v("POVPIP")
    rel = s.v("RELSHIPP")
    price_year = 12 * (PART_A_UNDER30Q + PART_B_STD)
    prof = {
        "n_records": int(rec.sum()),
        "count": round(w[rec].sum()),
        "count_se": round(s.total(rec)[1]),
        "median_personal_income": wmedian(pinc[rec], w[rec]),
        "share_personal_income_zero_or_less": pct(w[rec & (pinc <= 0)].sum() / w[rec].sum()),
        "share_personal_income_below_buyin": pct(w[rec & (pinc < price_year)].sum() / w[rec].sum()),
        "median_family_pct_poverty": wmedian(pov[rec & (pov >= 0)], w[rec & (pov >= 0)]),
        "share_family_below_138pct": pct(w[rec & (pov >= 0) & (pov < 138)].sum() / w[rec & (pov >= 0)].sum()),
        "share_family_at_or_above_200pct": pct(w[rec & (pov >= 200)].sum() / w[rec & (pov >= 0)].sum()),
        "share_parent_of_householder": pct(w[rec & ((rel == 29) | (rel == 31))].sum() / w[rec].sum()),
        "share_householder_or_spouse": pct(w[rec & ((rel >= 20) & (rel <= 24))].sum() / w[rec].sum()),
        "share_household_with_worker": pct(w[rec & (s.v("HHEMP") == 1)].sum() / w[rec].sum()),
        "share_not_well_or_not_at_all": pct(w[rec & ((s.eng == 3) | (s.eng == 4))].sum() / w[rec].sum()),
        "share_noncitizen": pct(w[rec & s.noncit].sum() / w[rec].sum()),
    }
    # same profile for all US-born 65+ for contrast
    usb = old & ~s.fb
    prof["usborn65_median_personal_income"] = wmedian(pinc[usb], w[usb])
    # country of birth among foreign-born uninsured 65+
    pob = s.v("POBP")
    fbu = old & s.fb & s.unins
    labels = dictionary("POBP", "2024")
    tot_fbu = w[fbu].sum()
    cnt = np.bincount(pob[fbu], weights=w[fbu])
    nn = np.bincount(pob[fbu])
    top = sorted(((cnt[c], c) for c in range(len(cnt)) if nn[c] >= 30), reverse=True)[:8]
    prof["top_birthplaces"] = [{"place": clean_pob(labels.get(c, str(c))), "share": pct(v / tot_fbu), "n": int(nn[c])}
                               for v, c in top]
    prof["fb_uninsured_65_pooled"] = round(tot_fbu)
    price = {
        "year": 2026,
        "part_a_under_30_quarters": PART_A_UNDER30Q,
        "part_a_30_39_quarters": PART_A_30_39Q,
        "part_b_standard": PART_B_STD,
        "monthly_full_buyin": round(PART_A_UNDER30Q + PART_B_STD, 2),
        "annual_full_buyin": round(price_year, 2),
        "profile_recent_uninsured_arrivals": prof,
    }
    (OUT / "price.json").write_text(json.dumps(price, indent=1))
    summary["price"] = price

    # 5. Dose-response by age at arrival, 65+ (5-year 2020-24) ----------------------
    s = F
    old = s.age >= 65
    dose = []
    for key, label, m in [("usborn", "Born in the US", ~s.fb),
                          ("arr_lt40", "Moved here before 40", s.fb & (s.arrage >= 0) & (s.arrage < 40)),
                          ("arr_40_54", "Moved here at 40–54", s.fb & (s.arrage >= 40) & (s.arrage < 55)),
                          ("arr_55p", "Moved here at 55 or older", s.fb & (s.arrage >= 55))]:
        r = s.one(old & m)
        sh_un = s.one(old & s.unins, m.astype(float))
        sh_all = s.one(old, m.astype(float))
        dose.append({"key": key, "label": label, "rate": pct(r["rate"], 2), "se": pct(r["se"], 3),
                     "share_of_seniors": pct(sh_all["rate"]), "share_of_uninsured": pct(sh_un["rate"])})
    summary["dose_5y"] = dose

    # 6. Language, 65+ with limited English (5-year 2020-24) -------------------------
    lanp = s.v("LANP")
    lab = dictionary("LANP", "2020-2024")
    codes = np.unique(lanp[old & s.lep & (lanp > 0)])
    code_ix = {c: i for i, c in enumerate(codes)}
    lix = np.array([code_ix.get(c, -1) for c in range(lanp.max() + 1)])
    lrows = []
    base = old & s.lep & (lanp > 0)
    for view, m in (("all", base), ("citizen", base & ~s.noncit), ("noncitizen", base & s.noncit)):
        cell = np.where(m, lix[np.maximum(lanp, 0)], -1)
        r = s.cells(cell, len(codes))
        for i, c in enumerate(codes):
            if r["n"][i] < 100:
                continue
            lo, hi = ci(r["rate"][i], r["se"][i])
            name = lab.get(int(c), str(c))
            residual = int(name.startswith("Other") or "N.E.C." in name or "unspecified" in name)
            lrows.append({"view": view, "code": int(c), "language": name, "residual": residual, "n": int(r["n"][i]),
                          "pop": round(r["pop"][i]), "rate": pct(r["rate"][i], 2), "se": pct(r["se"][i], 2),
                          "lo": lo, "hi": hi})
    padutch = [x for x in lrows if x["code"] == 1125]
    pam = base & (lanp == 1125)
    pa_native = pct(s.W[pam & ~s.fb, 0].sum(dtype=np.float64) / s.W[pam, 0].sum(dtype=np.float64))
    lrows = [x for x in lrows if x["code"] != 1125]
    write_csv(OUT / "lang65.csv", lrows, ["view", "code", "language", "residual", "n", "pop", "rate", "se", "lo", "hi"])
    eo = s.one(old & s.engonly)
    allep = s.one(base)
    summary["lang"] = {"english_only_65": pct(eo["rate"], 2), "english_only_65_se": pct(eo["se"], 3),
                       "all_lep_65": pct(allep["rate"], 2),
                       "pa_german_excluded": padutch,
                       "pa_german_us_born_share": pa_native,
                       "n_languages": {v: sum(1 for x in lrows if x["view"] == v) for v in ("all", "citizen", "noncitizen")}}
    summary["sources"] = {"one_year": [2022, 2023, 2024], "five_year": "2020-2024"}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps(summary, indent=1, default=float)[:6000])


def clean_pob(s):
    s = s.split("/")[0].strip()
    return s.replace(" (Other)", "")


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r[k]) for k in cols})


if __name__ == "__main__":
    main()
