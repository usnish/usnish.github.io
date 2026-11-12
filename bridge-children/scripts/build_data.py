"""Build the "bridge children" data.

A bridge child is a child aged 5-17 who speaks only English or speaks English
"very well", living in a household where every adult (18+) has limited English.
Counted from the ACS 2020-2024 5-year PUMS (person + housing files), with
standard errors from the 80 successive-difference replicate weights:
SE = sqrt(4/80 * sum((rep - est)^2)).

Definitions (ACS person variables):
  fluent             LANX == 2 (speaks only English) or ENG == 1 ("very well")
  LEP adult (HHS)    age 18+, LANX == 1 and ENG in {2,3,4} (well / not well / not at all)
  LEP adult (strict) age 18+, LANX == 1 and ENG in {3,4}   (not well / not at all)
  qualifying home    housing unit (no group quarters) with >= 1 adult, all adults LEP
  bridge child       age 5-17, fluent, in a qualifying home
  Census "limited English speaking household" = no member aged 14+ speaks only
  English or speaks it very well (LNGI on the housing file). In a qualifying home
  every adult is LEP, so the home is classed NOT limited-English exactly when a
  14-17-year-old is fluent. Computed both ways; the mismatch is reported.

Person counts use PWGTP; household counts use WGTP from the housing file.
Household language = the language (LANP) of the reference person, or of the
first adult listed if the reference person is under 18.

Also re-runs everything on the 2024 1-year file as a check, and reproduces the one
published comparison (Census Bureau 2019 poster, 2017 ACS) on the 2019 and 2024 1-year files.

Run (needs numpy):  python3 bridge-children/scripts/build_data.py
                    (or: uv run --with numpy --with scipy python3 bridge-children/scripts/build_data.py)
Writes data/summary.json, data/ages.csv, data/lang.csv, data/deps.json, data/states.csv
"""
import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent / "_viz"))
import vizlib  # noqa: E402

CACHE = vizlib.CACHE / "bridge"
CACHE.mkdir(exist_ok=True)
OUT = HERE / "data"
OUT.mkdir(exist_ok=True)

BASE = "https://www2.census.gov/programs-surveys/acs/data/pums/2024/"
FILES = {
    "5y": {"pus": (BASE + "5-Year/csv_pus.zip", "csv_pus_5y2024.zip"),
           "hus": (BASE + "5-Year/csv_hus.zip", "csv_hus_5y2024.zip")},
    "1y": {"pus": (BASE + "1-Year/csv_pus.zip", "csv_pus_1y2024.zip"),
           "hus": (BASE + "1-Year/csv_hus.zip", "csv_hus_1y2024.zip")},
}
POSTER_FILES = {"2019": (BASE.replace("2024", "2019") + "1-Year/csv_pus.zip", "csv_pus_1y2019.zip"),
                "2024": FILES["1y"]["pus"]}
DICT_URL = "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2020-2024.csv"

TIERS = ("hhs", "strict")
LANG_MIN_N = 100       # unweighted households in the denominator for a language row
STATE_MAX_CV = 0.30    # suppress state cells with a coefficient of variation above this
LANG_GROUPS = {"1970": "Chinese", "2000": "Chinese", "2030": "Chinese", "2050": "Chinese",
               "2910": "Tagalog/Filipino", "2920": "Tagalog/Filipino"}
STATES = {"01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas", "06": "California", "08": "Colorado",
          "09": "Connecticut", "10": "Delaware", "11": "District of Columbia", "12": "Florida", "13": "Georgia",
          "15": "Hawaii", "16": "Idaho", "17": "Illinois", "18": "Indiana", "19": "Iowa", "20": "Kansas",
          "21": "Kentucky", "22": "Louisiana", "23": "Maine", "24": "Maryland", "25": "Massachusetts",
          "26": "Michigan", "27": "Minnesota", "28": "Mississippi", "29": "Missouri", "30": "Montana",
          "31": "Nebraska", "32": "Nevada", "33": "New Hampshire", "34": "New Jersey", "35": "New Mexico",
          "36": "New York", "37": "North Carolina", "38": "North Dakota", "39": "Ohio", "40": "Oklahoma",
          "41": "Oregon", "42": "Pennsylvania", "44": "Rhode Island", "45": "South Carolina", "46": "South Dakota",
          "47": "Tennessee", "48": "Texas", "49": "Utah", "50": "Vermont", "51": "Virginia", "53": "Washington",
          "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming"}


def download(url, name):
    """Stream a (large) file into the cache once; return its path."""
    path = CACHE / name
    if path.exists():
        return path
    part = path.with_suffix(".part")
    print(f"  downloading {url}", flush=True)
    req = urllib.request.Request(url, headers=vizlib.UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 22):
            f.write(chunk)
    part.rename(path)
    return path


def members(zpath, prefix):
    with zipfile.ZipFile(zpath) as z:
        return sorted(n for n in z.namelist() if n.startswith(prefix) and n.endswith(".csv"))


def lines(zpath, member):
    z = zipfile.ZipFile(zpath)
    f = io.TextIOWrapper(z.open(member), encoding="latin-1", newline="")
    header = f.readline().rstrip("\r\n").split(",")
    return header, f


def rep_vector(fields, i0, i_reps):
    v = np.empty(81)
    v[0] = float(fields[i0])
    v[1:] = [float(fields[i]) for i in i_reps]
    return v


# Pass 1: persons ---------------------------------------------------------------

def person_pass(args):
    zpath, member = args
    header, f = lines(zpath, member)
    ix = {h: i for i, h in enumerate(header)}
    need = ["SERIALNO", "SPORDER", "AGEP", "LANX", "ENG", "RELSHIPP", "HINS4", "POVPIP", "STATE", "LANP", "NATIVITY", "PWGTP"]
    I = {k: ix[k] for k in need}
    maxi = max(I.values()) + 1
    i_w, i_reps = ix["PWGTP"], [ix[f"PWGTP{k}"] for k in range(1, 81)]

    acc = defaultdict(lambda: np.zeros(81))
    nobs = defaultdict(int)
    hh = {}   # serial -> household info for qualifying homes (HHS tier; strict is a subset)

    def add(key, w):
        acc[key] += w
        nobs[key] += 1

    def process(serial, rows):
        persons = []
        for line, p in rows:
            age = int(p[I["AGEP"]])
            persons.append({"line": line, "age": age, "lanx": p[I["LANX"]], "eng": p[I["ENG"]],
                            "rel": p[I["RELSHIPP"]], "hins4": p[I["HINS4"]], "pov": p[I["POVPIP"]],
                            "st": p[I["STATE"]], "lanp": p[I["LANP"]], "nat": p[I["NATIVITY"]],
                            "sp": int(p[I["SPORDER"]])})
        if persons[0]["rel"] in ("37", "38"):
            return
        for q in persons:
            q["fluent"] = q["age"] >= 5 and (q["lanx"] == "2" or q["eng"] == "1")
        kids = [q for q in persons if 5 <= q["age"] <= 17]
        adults = [q for q in persons if q["age"] >= 18]
        lep = bool(adults) and all(q["lanx"] == "1" and q["eng"] in ("2", "3", "4") for q in adults)
        for q in (persons if lep else kids):
            q["w"] = rep_vector(q["line"].split(","), i_w, i_reps)
        for q in kids:  # context denominator: all children 5-17 in housing units
            add("all_kids_5_17", q["w"])
        if not lep:
            return
        strict = all(q["eng"] in ("3", "4") for q in adults)
        ref = next((q for q in persons if q["rel"] == "20" and q["age"] >= 18), None) or min(adults, key=lambda q: q["sp"])
        lang = LANG_GROUPS.get(ref["lanp"], ref["lanp"])
        bridges = [q for q in kids if q["fluent"]]
        teen_fluent = any(q["fluent"] and q["age"] >= 14 for q in persons)
        info = {"strict": strict, "child": bool(kids), "bridge": bool(bridges), "teen": teen_fluent,
                "lang": lang, "st": ref["st"], "n_adults": len(adults)}
        hh[serial] = info
        for t in TIERS:
            if t == "strict" and not strict:
                continue
            for q in kids:
                add(f"kids_in_lep_home|{t}", q["w"])
            for q in adults:
                add(f"lep_adults|{t}", q["w"])
            if not bridges:
                continue
            sole = len(bridges) == 1
            for q in bridges:
                w = q["w"]
                add(f"bridge|{t}", w)
                add(f"bridge_age{q['age']}|{t}", w)
                add(f"bridge_{'missed' if teen_fluent else 'counted'}|{t}", w)
                if teen_fluent:  # by age, so the page can split each age into counted / not counted
                    add(f"bridge_missed_age{q['age']}|{t}", w)
                add(f"bridge_state{q['st']}|{t}", w)
                if sole:
                    add(f"bridge_sole|{t}", w)
                if q["nat"] == "1":
                    add(f"bridge_usborn|{t}", w)
                if q["hins4"] == "1":
                    add(f"bridge_medicaid|{t}", w)
                if q["pov"].strip():
                    pv = int(q["pov"])
                    add(f"bridge_pov_known|{t}", w)
                    if pv < 100:
                        add(f"bridge_pov100|{t}", w)
                    if pv < 200:
                        add(f"bridge_pov200|{t}", w)
            for q in adults:
                w = q["w"]
                add(f"dep|{t}", w)
                if q["hins4"] == "1":
                    add(f"dep_medicaid|{t}", w)
                if q["age"] >= 65:
                    add(f"dep_65|{t}", w)
                add(f"dep_eng{q['eng']}|{t}", w)
            for q in kids:
                if not q["fluent"]:
                    add(f"kids_not_fluent_in_bridge_home|{t}", q["w"])

    cur, rows = None, []
    t0 = time.time()
    n = 0
    for line in f:
        p = line.split(",", maxi)
        s = p[I["SERIALNO"]]
        if s != cur:
            if rows:
                process(cur, rows)
            cur, rows = s, []
        rows.append((line, p))
        n += 1
        if n % 2_000_000 == 0:
            print(f"    {member}: {n:,} persons, {time.time() - t0:.0f}s", flush=True)
    if rows:
        process(cur, rows)
    return dict(acc), dict(nobs), hh


# Pass 2: housing weights for qualifying homes -------------------------------------

def housing_pass(args):
    zpath, member, serials = args
    header, f = lines(zpath, member)
    ix = {h: i for i, h in enumerate(header)}
    i_s, i_w, i_l = ix["SERIALNO"], ix["WGTP"], ix["LNGI"]
    i_reps = [ix[f"WGTP{k}"] for k in range(1, 81)]
    out = {}
    for line in f:
        s = line[:line.index(",", line.index(",") + 1)].split(",")[1]
        if s in serials:
            p = line.rstrip("\r\n").split(",")
            out[s] = (rep_vector(p, i_w, i_reps), p[i_l])
    return out


# Check against the one published figure: Dietrich & Bauman (Census Bureau, PAA 2019 poster,
# 2017 ACS) report that 20.7% of English-fluent children 5-17 in homes with an adult who speaks
# another language live where every adult speaks English less than "very well".

def poster_pass(args):
    zpath, member = args
    header, f = lines(zpath, member)
    ix = {h: i for i, h in enumerate(header)}
    S_, A, L, E, R, W = (ix[k] for k in ("SERIALNO", "AGEP", "LANX", "ENG", "RELSHIPP", "PWGTP"))
    mx = max(S_, A, L, E, R, W) + 1
    tot = [0.0, 0.0]

    def proc(rows):
        if not rows or rows[0][R] in ("37", "38"):
            return
        adults = [p for p in rows if int(p[A]) >= 18]
        if not any(p[L] == "1" for p in adults):
            return
        allless = all(p[L] == "1" and p[E] in ("2", "3", "4") for p in adults)
        for p in rows:
            if 5 <= int(p[A]) <= 17 and (p[L] == "2" or p[E] == "1"):
                tot[0] += float(p[W])
                if allless:
                    tot[1] += float(p[W])
    cur, rows = None, []
    for line in f:
        p = line.split(",", mx)
        if p[S_] != cur:
            proc(rows)
            cur, rows = p[S_], []
        rows.append(p)
    proc(rows)
    return tot


def poster_check():
    out = {"published_2017": 0.207}
    for yr, (url, name) in POSTER_FILES.items():
        z = download(url, name)
        with ProcessPoolExecutor() as ex:
            parts = list(ex.map(poster_pass, [(str(z), m) for m in members(z, "psam_pus")]))
        den, num = sum(p[0] for p in parts), sum(p[1] for p in parts)
        out[yr] = {"share": round(num / den, 4), "fluent_kids_in_lote_adult_homes": round(den), "bridge_children": round(num)}
        print(f"poster check {yr}: {num / den:.3f}", flush=True)
    return out


def se(v):
    return float(np.sqrt(4 / 80 * np.sum((v[1:] - v[0]) ** 2)))


def ratio(num, den):
    r = np.divide(num, den, out=np.zeros(81), where=den > 0)
    return float(r[0]), se(r)


def run(which):
    pus = download(*FILES[which]["pus"])
    hus = download(*FILES[which]["hus"])
    pm = members(pus, "psam_pus")
    print(f"[{which}] person files: {pm}", flush=True)
    acc, nobs, hh = defaultdict(lambda: np.zeros(81)), defaultdict(int), {}

    with ProcessPoolExecutor(max_workers=len(pm)) as ex:
        for a, n, h in ex.map(person_pass, [(str(pus), m) for m in pm]):
            for k, v in a.items():
                acc[k] += v
            for k, v in n.items():
                nobs[k] += v
            hh.update(h)
    print(f"[{which}] qualifying homes in sample: {len(hh):,}", flush=True)

    hm = members(hus, "psam_hus")
    serials = set(hh)
    hw = {}
    with ProcessPoolExecutor(max_workers=len(hm)) as ex:
        for part in ex.map(housing_pass, [(str(hus), m, serials) for m in hm]):
            hw.update(part)
    missing = len(serials - set(hw))
    print(f"[{which}] housing weights matched: {len(hw):,}, missing {missing}", flush=True)

    hacc = defaultdict(lambda: np.zeros(81))
    hn = defaultdict(int)
    lngi_mismatch = 0
    for s, info in hh.items():
        if s not in hw:
            continue
        w, lngi = hw[s]
        official_limited = not info["teen"]
        if lngi in ("1", "2") and (lngi == "2") != official_limited:  # LNGI 2 = limited English household
            lngi_mismatch += 1
        for t in TIERS:
            if t == "strict" and not info["strict"]:
                continue
            keys = [f"hh_lep|{t}"]
            if info["child"]:
                keys += [f"hh_child|{t}", f"hh_child|{t}|{info['lang']}"]
                if info["bridge"]:
                    keys += [f"hh_child_bridge|{t}", f"hh_child_bridge|{t}|{info['lang']}"]
            if info["bridge"]:
                keys.append(f"hh_bridge|{t}")
                keys.append(f"hh_bridge_{'missed' if info['teen'] else 'counted'}|{t}")
                keys.append(f"hh_bridge_lngi{lngi}|{t}")
            for k in keys:
                hacc[k] += w
                hn[k] += 1
    print(f"[{which}] my official flag vs Census LNGI mismatches: {lngi_mismatch}", flush=True)
    return acc, nobs, hacc, hn, lngi_mismatch, len(hh)


def lanp_labels():
    path = download(DICT_URL, "PUMS_Data_Dictionary_2020-2024.csv")
    lab = {}
    with open(path, newline="", encoding="latin-1") as f:
        for r in csv.reader(f):
            if len(r) >= 7 and r[0] == "VAL" and r[1] == "LANP":
                lab[r[4]] = r[6]
    lab.update({v: v for v in LANG_GROUPS.values()})
    return lab


def est(acc, key):
    v = acc.get(key)
    if v is None:
        return {"est": 0, "se": 0}
    return {"est": round(float(v[0])), "se": round(se(v))}


def summarize(acc, nobs, hacc, hn, mismatch, nhh):
    S = {}
    for t in TIERS:
        g = lambda k: acc.get(f"{k}|{t}", np.zeros(81))  # noqa: E731
        h = lambda k: hacc.get(f"{k}|{t}", np.zeros(81))  # noqa: E731
        b = g("bridge")
        le13 = sum(g(f"bridge_age{a}") for a in range(5, 14))
        d = {
            "bridge_children": est(acc, f"bridge|{t}"),
            "bridge_children_n": nobs.get(f"bridge|{t}", 0),
            "age_5_9": {"est": round(float(sum(g(f'bridge_age{a}') for a in range(5, 10))[0]))},
            "age_10_13": {"est": round(float(sum(g(f'bridge_age{a}') for a in range(10, 14))[0]))},
            "age_14_17": {"est": round(float(sum(g(f'bridge_age{a}') for a in range(14, 18))[0]))},
            "age_le13_share": ratio(le13, b),
            "counted_by_census": est(acc, f"bridge_counted|{t}"),
            "missed_by_census": est(acc, f"bridge_missed|{t}"),
            "missed_share": ratio(g("bridge_missed"), b),
            "sole_fluent_share": ratio(g("bridge_sole"), b),
            "us_born_share": ratio(g("bridge_usborn"), b),
            "medicaid_share": ratio(g("bridge_medicaid"), b),
            "below_poverty_share": ratio(g("bridge_pov100"), g("bridge_pov_known")),
            "below_200fpl_share": ratio(g("bridge_pov200"), g("bridge_pov_known")),
            "share_of_kids_in_lep_homes": ratio(b, g("kids_in_lep_home")),
            "share_of_all_kids_5_17": ratio(b, acc["all_kids_5_17"]),
            "households_with_child": est(hacc, f"hh_child|{t}"),
            "households_with_bridge": est(hacc, f"hh_bridge|{t}"),
            "households_bridge_missed": est(hacc, f"hh_bridge_missed|{t}"),
            "households_bridge_counted": est(hacc, f"hh_bridge_counted|{t}"),
            "rate_bridge_given_child": ratio(h("hh_child_bridge"), h("hh_child")),
            "dependent_adults": est(acc, f"dep|{t}"),
            "dependent_adults_medicaid": est(acc, f"dep_medicaid|{t}"),
            "dependent_adults_65plus": est(acc, f"dep_65|{t}"),
            "dependent_adults_eng_well_share": ratio(g("dep_eng2"), g("dep")),
            "dependent_adults_eng_notwell_share": ratio(g("dep_eng3"), g("dep")),
            "dependent_adults_eng_notatall_share": ratio(g("dep_eng4"), g("dep")),
            "lep_adults_all": est(acc, f"lep_adults|{t}"),
        }
        for k in list(d):
            if isinstance(d[k], tuple):
                d[k] = {"est": round(d[k][0], 4), "se": round(d[k][1], 4)}
        S[t] = d
    S["all_kids_5_17"] = est(acc, "all_kids_5_17")
    S["lngi_mismatch_households"] = mismatch
    S["sample_households"] = nhh  # sampled homes where every adult has limited English (standard definition)
    return S


def main():
    labels = lanp_labels()
    acc, nobs, hacc, hn, mm, nhh = run("5y")
    S = {"source": "ACS 2020-2024 5-year PUMS (U.S. Census Bureau), persons in housing units",
         "built": time.strftime("%Y-%m-%d"), **summarize(acc, nobs, hacc, hn, mm, nhh)}

    # ages
    rows = []
    for a in range(5, 18):
        r = {"age": a}
        for t in TIERS:
            e = est(acc, f"bridge_age{a}|{t}")
            r[t], r[t + "_se"] = e["est"], e["se"]
            r[t + "_missed"] = est(acc, f"bridge_missed_age{a}|{t}")["est"]  # in a home not classed limited-English
        rows.append(r)
    vizlib.write_csv(OUT / "ages.csv", rows, ["age", "hhs", "hhs_se", "hhs_missed", "strict", "strict_se", "strict_missed"])

    # languages (rate among all-LEP-adult homes with a child 5-17)
    langs = sorted({k.split("|")[2] for k in hn if k.startswith("hh_child|hhs|")})
    rows = []
    for L in langs:
        r = {"lang": labels.get(L, L)}
        ok = False
        for t in TIERS:
            den, num = hacc.get(f"hh_child|{t}|{L}"), hacc.get(f"hh_child_bridge|{t}|{L}", np.zeros(81))
            n = hn.get(f"hh_child|{t}|{L}", 0)
            if den is None or n < LANG_MIN_N:
                r.update({f"{t}_rate": "", f"{t}_se": "", f"{t}_n": n, f"{t}_homes": ""})
                continue
            ok = ok or t == "hhs"
            rr, s = ratio(num, den)
            r.update({f"{t}_rate": round(rr, 4), f"{t}_se": round(s, 4), f"{t}_n": n, f"{t}_homes": round(float(den[0]))})
        if ok:
            rows.append(r)
    rows.sort(key=lambda r: -r["hhs_homes"])
    vizlib.write_csv(OUT / "lang.csv", rows, ["lang", "hhs_rate", "hhs_se", "hhs_n", "hhs_homes",
                                               "strict_rate", "strict_se", "strict_n", "strict_homes"])
    print(f"languages with >= {LANG_MIN_N} sample homes: {len(rows)}")

    # states
    rows = []
    for st, name in STATES.items():
        r = {"fips": st, "state": name}
        for t in TIERS:
            e = est(acc, f"bridge_state{st}|{t}")
            cv = e["se"] / e["est"] if e["est"] else 9
            r[t], r[t + "_se"] = (e["est"], e["se"]) if cv <= STATE_MAX_CV else ("", "")
        rows.append(r)
    vizlib.write_csv(OUT / "states.csv", rows, ["fips", "state", "hhs", "hhs_se", "strict", "strict_se"])

    deps = {t: {k: S[t][k] for k in S[t] if k.startswith("dependent_")} for t in TIERS}
    (OUT / "deps.json").write_text(json.dumps(deps, indent=1))

    # 1-year check
    acc1, nobs1, hacc1, hn1, mm1, nhh1 = run("1y")
    S1 = summarize(acc1, nobs1, hacc1, hn1, mm1, nhh1)
    S["check_2024_1yr"] = {t: {k: S1[t][k] for k in ("bridge_children", "missed_share", "age_le13_share",
                                                      "rate_bridge_given_child", "counted_by_census")}
                           for t in TIERS}
    S["check_2024_1yr"]["source"] = "ACS 2024 1-year PUMS"
    S["check_census_poster"] = poster_check()
    (OUT / "summary.json").write_text(json.dumps(S, indent=1))
    print(json.dumps({t: {k: S[t][k] for k in ("bridge_children", "missed_share", "rate_bridge_given_child")} for t in TIERS}, indent=1))


if __name__ == "__main__":
    main()
