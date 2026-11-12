"""Build the data for "Noisy ruler, real differences" (Medicare's readmission penalties).

Sources (all public, no login):
  1. CMS FY2026 Hospital Readmissions Reduction Program (HRRP) supplemental file
     (final rule): per-hospital ERR, peer-group median, penalty flag, DRG payment
     ratio and payment reduction. Discharges 7/1/2021-6/30/2024.
  2. CMS FY2023 HRRP supplemental file (discharges 7/1/2018-12/1/2019 and
     7/1/2020-6/30/2021; CMS dropped the first half of 2020. The non-overlapping
     earlier window; pneumonia was suppressed that year).
  3. CMS Provider Data Catalog dataset 9n3s-kdb3 (FY2026 HRRP, hospital level):
     names, predicted and expected readmission rates and readmission counts.
  4. CMS FY2027 HRRP supplemental file, for context only (window 7/2023-6/2025
     overlaps FY2026's and adds Medicare Advantage stays).

Method in brief
  * CMS shrinks each hospital's readmission rate toward the national average with
    a hierarchical logistic model. We emulate that shrinkage with one number per
    condition, k:   predicted - expected = n/(n+k) * (observed/n - expected),
    fitted to CMS's own published predicted and expected rates. n/(n+k) is the
    measure's reliability for a hospital with n discharges. The spread of true
    hospital ratios that the same model implies is tau^2 = (1-E)/(E*k).
  * Lineup: chance-only panels put every hospital at exactly its expected rate,
    draw readmissions from Binomial(n, E), apply the same shrinkage, recompute ERR.
  * Per hospital: P(true ratio > peer median) from a normal approximation to the
    posterior (mean = published ERR, variance = tau^2 * (1 - reliability)),
    checked for calibration by simulation.
  * Persistence: FY2023 vs FY2026 ERR correlation, against the ceiling that
    measurement noise alone allows if every hospital's true ratio never changed.

Writes data/hospitals.json, data/lineup.json, data/summary.json.
Usage: uv run --with numpy --with scipy python3 readmission-noise/scripts/build_data.py
"""
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)

FY26_ZIP = "https://www.cms.gov/files/zip/fy2026-hospital-readmissions-reduction-program-supplemental-data-file.zip"
FY23_ZIP = "https://www.cms.gov/files/zip/fy-2023-ipps-final-rule-hrrp-supplemental-file.zip"
FY26_TXT = "FR FY 2026.txt"
FY23_TXT = "FY2023_FR_Supplemental_File FR FY 2023.txt"
# Newest year, shown for context only: its window (7/2023-6/2025) overlaps FY2026's, it adds Medicare
# Advantage stays, and CMS has not yet published its hospital-level predicted/expected rates.
FY27_ZIP = "https://www.cms.gov/files/zip/fy-2027-hospital-readmissions-reduction-program-supplemental-data-file.zip"
FY27_TXT = "FY2027_HRRP_Supplemental_File - FR FY 2027 Tab.txt"
PDC_API = "https://data.cms.gov/provider-data/api/1/datastore/query/9n3s-kdb3/0"
PDC_PAGE = 1500

# Display order: cardiac first
CONDS = ["HF", "AMI", "COPD", "PN", "CABG", "THA"]
FILE_NAME = {"HF": "HF", "AMI": "AMI", "COPD": "COPD", "PN": "pneumonia", "CABG": "CABG", "THA": "THA/TKA"}
MEASURE = {"READM-30-AMI-HRRP": "AMI", "READM-30-COPD-HRRP": "COPD", "READM-30-HF-HRRP": "HF",
           "READM-30-PN-HRRP": "PN", "READM-30-CABG-HRRP": "CABG", "READM-30-HIP-KNEE-HRRP": "THA"}
LABEL = {"HF": "Heart failure", "AMI": "Heart attack (AMI)", "COPD": "COPD", "PN": "Pneumonia",
         "CABG": "Bypass surgery (CABG)", "THA": "Hip/knee replacement"}
MIN_N = 25          # measures with fewer eligible discharges don't count toward the penalty
CAP = 0.03          # maximum payment reduction
N_NULL_PANELS = 8   # chance-only panels per condition in the lineup
SEED = 20261111

rng = np.random.default_rng(SEED)


def check(name, value, target, tol):
    ok = abs(value - target) <= tol
    print(f"  {'ok ' if ok else 'FAIL'} {name}: {value:.4f} (target {target} +/- {tol})")
    if not ok:
        raise SystemExit(f"assertion failed: {name}")


# ---------------------------------------------------------------- load ------

def fl(x):
    x = (x or "").strip().replace(",", "").replace('"', "")
    if x in ("", "."):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def load_supplemental(url, cache_name, member):
    """Tab-delimited, latin-1, title lines before the header row that starts 'Hospital CCN'."""
    with zipfile.ZipFile(V.fetch(url, cache_name)) as z:
        text = z.read(member).decode("latin-1")
    rows = [r.split("\t") for r in text.splitlines()]
    hi = next(i for i, r in enumerate(rows) if r and r[0].strip().startswith("Hospital CCN"))
    head = [h.strip() for h in rows[hi]]
    col = {h: i for i, h in enumerate(head)}
    out = {}
    for r in rows[hi + 1:]:
        ccn = r[0].strip()
        if len(ccn) != 6 or len(r) < 10:
            continue
        g = lambda h: r[col[h]] if h in col and col[h] < len(r) else ""  # noqa: E731
        h = {"paf": fl(g("Payment adjustment factor")), "red": float(g("Payment reduction percentage").strip().rstrip("%")),
             "dual": fl(g("Dual proportion")), "pg": int(g("Peer group assignment")), "nm": fl(g("Neutrality modifier")), "c": {}}
        for c in CONDS:
            f = FILE_NAME[c]
            if f"ERR for {f}" not in col:
                continue
            h["c"][c] = {"n": fl(g(f"Number of eligible discharges for {f}")), "err": fl(g(f"ERR for {f}")),
                         "med": fl(g(f"Peer group median ERR for {f}")), "pen": g(f"Penalty indicator for {f}").strip() == "Y",
                         "w": fl(g(f"DRG payment ratio for {f}"))}
        out[ccn] = h
    return out


def load_provider():
    """FY2026 hospital-level HRRP rows from the Provider Data Catalog datastore API (cached)."""
    path = V.CACHE / "hrrp_fy2026_provider_9n3s-kdb3.json"
    if path.exists():
        rows = json.loads(path.read_text())
    else:
        rows, off = [], 0
        while True:
            j = V.get_json(PDC_API, {"limit": PDC_PAGE, "offset": off})
            rows += j["results"]
            off += PDC_PAGE
            if off >= j["count"]:
                break
        assert len(rows) == j["count"], (len(rows), j["count"])
        path.write_text(json.dumps(rows))
    out = {}
    for r in rows:
        c = MEASURE.get(r["measure_name"])
        if not c:
            continue
        d = {"name": r["facility_name"], "state": r["state"], "n": fl(r["number_of_discharges"]),
             "err": fl(r["excess_readmission_ratio"]), "P": fl(r["predicted_readmission_rate"]),
             "E": fl(r["expected_readmission_rate"]), "o": fl(r["number_of_readmissions"]),
             "too_few": r["number_of_readmissions"].strip() == "Too Few to Report"}
        out[(r["facility_id"], c)] = d
    return rows, out


SMALL = {"Of", "And", "The", "For", "At", "In", "On"}
UPPER = {"Llc", "Ii", "Iii", "Usa", "Va", "Ucsf", "Ucla", "Uc", "Uab", "Ohsu", "Hca", "Sts", "Mcallen", "Nyu", "Unc", "Upmc",
         "Lds", "Smc", "Cmc", "Ssm", "Osf", "Uh", "Uw", "Ut", "Ou", "Ochsner", "Mmc", "Ahn", "Arh", "Bsa", "Cgh",
         "Chi", "Cjw", "Dch", "Dlp", "Ecu", "Fhn", "Ihs", "Iu", "Jfk", "Jps", "Lmh", "Lsu", "Mdl", "Nmc", "Phs", "Pih", "Rmh",
         "Tj", "Ucf", "Uci", "Uf", "Unm", "Usc", "Usd", "Uva", "Vcu", "Vhs", "Wca", "Mcg", "Ahs", "Mclaren"}


def tidy_name(s):
    words = []
    for i, w in enumerate(s.strip().title().split()):
        w = w.replace("'S", "'s")
        if i and w in SMALL:
            w = w.lower()
        elif w in UPPER and w not in ("Ochsner", "Mcallen", "Mclaren"):
            w = w.upper()
        elif w in ("Mcallen", "Mclaren"):
            w = "Mc" + w[2:].capitalize()
        words.append(w)
    return " ".join(words)


print("Loading CMS files")
f26 = load_supplemental(FY26_ZIP, "hrrp_fy2026_supplemental.zip", FY26_TXT)
f23 = load_supplemental(FY23_ZIP, "hrrp_fy2023_supplemental.zip", FY23_TXT)
f27 = load_supplemental(FY27_ZIP, "hrrp_fy2027_supplemental.zip", FY27_TXT)
red27 = np.array([h["red"] for h in f27.values()])
print(f"  FY2027 (context): {len(f27)} hospitals, {(red27 > 0).sum()} penalized ({(red27 > 0).mean():.3f})")
prov_rows, prov = load_provider()
print(f"  FY2026 hospitals {len(f26)}, FY2023 hospitals {len(f23)}, provider rows {len(prov_rows)}")
check("FY2026 hospitals", len(f26), 2945, 0)
check("FY2023 hospitals", len(f23), 3044, 0)
check("provider rows", len(prov_rows), 18330, 0)
CCNS = list(f26)

# ------------------------------------------------- program headline numbers --
print("FY2026 program")
red = np.array([f26[c]["red"] for c in CCNS])
pen_share = (red > 0).mean()
med_pen = float(np.median(red[red > 0]))
ge1 = (red >= 1).mean()
at_cap = int((red >= 2.995).sum())
check("share penalized", pen_share, 0.782, 0.0006)
check("median reduction among penalized (%)", med_pen, 0.30, 0.005)
check("share at 1% or more", ge1, 0.081, 0.0006)
check("hospitals at the 3% cap", at_cap, 15, 0)


def reduction(h, errs=None, meds=None):
    s = 0.0
    for c in CONDS:
        d = h["c"].get(c)
        if not d or d["n"] is None or d["n"] < MIN_N or d["w"] is None:
            continue
        e = d["err"] if errs is None else errs[c]
        m = d["med"] if meds is None else meds[c]
        s += d["w"] * max(e - m, 0)
    return min(s * h["nm"], CAP) * 100


recomputed = np.array([reduction(f26[c]) for c in CCNS])
max_diff = float(np.abs(recomputed - red).max())
check("max |recomputed - CMS reduction| (points)", max_diff, 0.00325, 0.00325)

n_elig = np.array([sum(1 for c in CONDS if f26[h]["c"][c]["n"] and f26[h]["c"][c]["n"] >= MIN_N and f26[h]["c"][c]["w"])
                   for h in CCNS])
by_elig = {}
for k in range(0, 7):
    m = n_elig == k
    if m.sum():
        by_elig[k] = {"hospitals": int(m.sum()), "penalized_share": round(float((red[m] > 0).mean()), 4)}
print("  penalized by # eligible conditions", {k: v["penalized_share"] for k, v in by_elig.items()})
check("penalized share, 1 eligible condition", by_elig[1]["penalized_share"], 0.37, 0.02)
check("penalized share, 6 eligible conditions", by_elig[6]["penalized_share"], 0.92, 0.02)

# ----------------------------------------------------------- shrinkage k ----
print("Shrinkage fit: (P - E) = n/(n+k) * (O/n - E)")


def fit_k(n, raw, sh):
    f = lambda k: np.sum((sh - n / (n + k) * raw) ** 2)  # noqa: E731
    return minimize_scalar(f, bounds=(5, 5000), method="bounded", options={"xatol": 0.05}).x


KFIT = {}
fit_rows = {}
for c in CONDS:
    rows = [(d["n"], d["o"], d["P"] / 100, d["E"] / 100) for (ccn, cc), d in prov.items()
            if cc == c and d["n"] and d["o"] is not None and d["P"] is not None and d["E"] is not None]
    a = np.array(rows, float)
    n, o, P, E = a.T
    raw, sh = o / n - E, P - E
    k = fit_k(n, raw, sh)
    r2 = 1 - np.sum((sh - n / (n + k) * raw) ** 2) / np.sum((sh - sh.mean()) ** 2)
    boots = []
    for _ in range(400):
        i = rng.integers(0, len(n), len(n))
        boots.append(fit_k(n[i], raw[i], sh[i]))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # Small-hospital check: hospitals with suppressed counts (<11 readmissions) are not in the fit.
    # Invert the fitted shrinkage to recover their implied count, which should land in 0-10.
    sup = [(f26[ccn]["c"][c]["n"], d["P"] / 100, d["E"] / 100) for (ccn, cc), d in prov.items()
           if cc == c and d["too_few"] and d["P"] is not None and d["E"] is not None and ccn in f26
           and f26[ccn]["c"][c]["n"] and f26[ccn]["c"][c]["n"] >= MIN_N]
    if sup:
        s = np.array(sup, float)
        lam = s[:, 0] / (s[:, 0] + k)
        o_imp = s[:, 0] * (s[:, 2] + (s[:, 1] - s[:, 2]) / lam)
        sup_ok = float(np.mean((o_imp > -0.5) & (o_imp < 10.5)))
    else:
        sup_ok = None
    KFIT[c] = {"k": round(float(k), 1), "k_lo": round(float(lo), 1), "k_hi": round(float(hi), 1), "r2": round(float(r2), 4),
               "fit_rows": int(len(n)), "fit_median_n": int(np.median(n)),
               "suppressed_rows": len(sup), "suppressed_implied_0_10": None if sup_ok is None else round(sup_ok, 3)}
    fit_rows[c] = (n, o, P, E)
    print(f"  {c}: k={k:.0f} (bootstrap 95% {lo:.0f}-{hi:.0f}), R2={r2:.4f}, rows={len(n)}, "
          f"suppressed rows {len(sup)} with implied count in 0-10: {sup_ok}")
for c, t in dict(AMI=370, COPD=395, HF=370, PN=415, CABG=230, THA=190).items():
    check(f"k {c}", KFIT[c]["k"], t, 12)
    check(f"R2 {c}", KFIT[c]["r2"], 0.996, 0.003)


def kval(c, which="k"):
    return KFIT[c][which]


# ------------------------------------------- per-condition hospital arrays --
def cond_arrays(c, k=None):
    """Hospitals with an ERR, >= 25 discharges and a published expected rate."""
    k = k or kval(c)
    idx, n, E, err, pg, med, pen, w = [], [], [], [], [], [], [], []
    for i, ccn in enumerate(CCNS):
        d = f26[ccn]["c"][c]
        p = prov.get((ccn, c))
        if d["n"] is None or d["n"] < MIN_N or d["err"] is None or not p or p["E"] is None:
            continue
        idx.append(i); n.append(d["n"]); E.append(p["E"] / 100); err.append(d["err"])
        pg.append(f26[ccn]["pg"]); med.append(d["med"]); pen.append(d["pen"]); w.append(d["w"] or 0.0)
    A = {k_: np.array(v) for k_, v in dict(idx=idx, n=n, E=E, err=err, pg=pg, med=med, pen=pen, w=w).items()}
    A["n"] = A["n"].astype(int)
    A["lam"] = A["n"] / (A["n"] + k)
    A["tau2"] = (1 - A["E"]) / (A["E"] * k)       # spread of true ratios the shrinkage implies
    A["post_sd"] = np.sqrt(A["tau2"] * (1 - A["lam"]))
    return A


ARR = {c: cond_arrays(c) for c in CONDS}
for c in CONDS:
    A = ARR[c]
    miss = sum(1 for ccn in CCNS if f26[ccn]["c"][c]["n"] and f26[ccn]["c"][c]["n"] >= MIN_N and f26[ccn]["c"][c]["err"] is not None) - len(A["n"])
    print(f"  {c}: {len(A['n'])} hospitals with >= 25 discharges and an expected rate ({miss} lack one)")


def shrink(o, n, E, lam):
    return 1 + lam * (o / (n * E) - 1)


def peer_medians(err, pg):
    med = np.empty_like(err)
    for g in range(1, 6):
        m = pg == g
        med[m] = np.median(err[m])
    return med


# --------------------------------------------- chance-only (null) worlds ----
print("Chance-only worlds: every hospital at its expected rate")
real_null_sd = {}
for c in CONDS:
    A = ARR[c]
    sds = [shrink(rng.binomial(A["n"], A["E"]), A["n"], A["E"], A["lam"]).std() for _ in range(200)]
    real_null_sd[c] = round(float(A["err"].std() / np.mean(sds)), 3)
    # Same ratio under the bootstrap ends of k
    lo_hi = []
    for kk in (kval(c, "k_lo"), kval(c, "k_hi")):
        lam = A["n"] / (A["n"] + kk)
        lo_hi.append(float(A["err"].std() / np.mean([shrink(rng.binomial(A["n"], A["E"]), A["n"], A["E"], lam).std() for _ in range(100)])))
    KFIT[c]["sd_ratio_k_range"] = [round(min(lo_hi), 3), round(max(lo_hi), 3)]
print("  real/null SD ratio", real_null_sd)
for c, t in dict(HF=1.37, PN=1.29, AMI=1.18, THA=1.17, CABG=1.16, COPD=1.11).items():
    check(f"SD ratio {c}", real_null_sd[c], t, 0.02)

# Lineup panels
lineup = {"seed": SEED, "panels": N_NULL_PANELS, "conds": {}}
for c in CONDS:
    A = ARR[c]
    nulls = []
    for _ in range(N_NULL_PANELS):
        e = shrink(rng.binomial(A["n"], A["E"]), A["n"], A["E"], A["lam"])
        nulls.append([int(round((v - 1) * 1000)) for v in e])  # thousandths above/below 1.000
    # Pointwise 95% chance band of the published-style ERR by n (for after the reveal)
    grid = np.unique(np.round(np.geomspace(MIN_N, A["n"].max(), 40)).astype(int))
    Ebar = float(np.median(A["E"]))
    lam_g = grid / (grid + kval(c))
    sims = shrink(rng.binomial(grid[:, None], Ebar, (len(grid), 4000)), grid[:, None], Ebar, lam_g[:, None])
    band = np.percentile(sims, [2.5, 97.5], axis=1)
    lo95 = np.interp(A["n"], grid, band[0])
    hi95 = np.interp(A["n"], grid, band[1])
    out_real = float(np.mean((A["err"] < lo95) | (A["err"] > hi95)))
    out_null = float(np.mean([np.mean((np.array(p) / 1000 + 1 < lo95) | (np.array(p) / 1000 + 1 > hi95)) for p in nulls]))
    lineup["conds"][c] = {"idx": A["idx"].tolist(), "n": A["n"].tolist(), "null": nulls,
                          "band": {"n": grid.tolist(), "lo": np.round(band[0], 4).tolist(), "hi": np.round(band[1], 4).tolist(),
                                   "expected_rate": round(Ebar, 4)},
                          "outside_band_real": round(out_real, 4), "outside_band_null": round(out_null, 4)}
    print(f"  {c}: outside chance band real {out_real:.3f} vs chance panels {out_null:.3f}")

# Whole-program chance world: what share would be penalized if every hospital were average?
pg_all = np.array([f26[c]["pg"] for c in CCNS])
nm_all = np.array([f26[c]["nm"] for c in CCNS])
null_pen = []
for _ in range(200):
    tot = np.zeros(len(CCNS))
    for c in CONDS:
        A = ARR[c]
        e = shrink(rng.binomial(A["n"], A["E"]), A["n"], A["E"], A["lam"])
        med = peer_medians(e, A["pg"])
        tot[A["idx"]] += A["w"] * np.maximum(e - med, 0)
    null_pen.append(float((np.minimum(tot * nm_all, CAP) > 0).mean()))
null_pen_share = float(np.mean(null_pen))
print(f"  chance-only world: {null_pen_share:.3f} of hospitals penalized")

# Cross-condition correlation of real ERRs within hospitals (why real < chance-only share)
errmat = {c: dict(zip(ARR[c]["idx"].tolist(), ARR[c]["err"].tolist())) for c in CONDS}
pair_r = []
for i, a in enumerate(CONDS):
    for b in CONDS[i + 1:]:
        common = sorted(set(errmat[a]) & set(errmat[b]))
        pair_r.append(np.corrcoef([errmat[a][j] for j in common], [errmat[b][j] for j in common])[0, 1])
mean_cross_r = float(np.mean(pair_r))
print(f"  mean pairwise correlation of a hospital's ERRs across conditions: {mean_cross_r:.3f}")

# ------------------------------------------- P(true ratio > peer median) ----
print("Posterior probability that the true ratio exceeds the peer median")
for c in CONDS:
    A = ARR[c]
    A["p_above"] = 1 - norm.cdf((A["med"] - A["err"]) / A["post_sd"])

# Calibration: simulate worlds that follow the model, compute the same probability, compare with truth
calib = {}
BINS = np.array([0, .1, .25, .5, .75, .9, 1.0001])
for c in CONDS:
    A = ARR[c]
    pred_all, hit_all = [], []
    for _ in range(100):
        theta = 1 + np.sqrt(A["tau2"]) * rng.standard_normal(len(A["n"]))
        o = rng.binomial(A["n"], np.clip(A["E"] * theta, 0, 1))
        e = shrink(o, A["n"], A["E"], A["lam"])
        med = peer_medians(e, A["pg"])
        p = 1 - norm.cdf((med - e) / A["post_sd"])
        pred_all.append(p); hit_all.append(theta > med)
    p = np.concatenate(pred_all); h = np.concatenate(hit_all)
    rows = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        m = (p >= lo) & (p < hi)
        rows.append({"bin": [round(float(lo), 2), round(float(min(hi, 1)), 2)], "mean_predicted": round(float(p[m].mean()), 3),
                     "observed": round(float(h[m].mean()), 3), "share": round(float(m.mean()), 3)})
    calib[c] = {"bins": rows, "brier": round(float(np.mean((p - h) ** 2)), 4),
                "max_gap": round(max(abs(r["mean_predicted"] - r["observed"]) for r in rows), 3)}
    print(f"  {c}: calibration max gap {calib[c]['max_gap']}, Brier {calib[c]['brier']}")

# Penalized hospitals by probability band, with sensitivity to the k range
p_bands = {}
for c in CONDS:
    A = ARR[c]
    pen = A["pen"].astype(bool)

    def bands(p):
        return {"ge90": round(float((p[pen] >= .9).mean()), 3), "lt75": round(float((p[pen] < .75).mean()), 3),
                "ge50": round(float((p[pen] >= .5).mean()), 3)}
    sens = []
    for kk in (kval(c, "k_lo"), kval(c, "k_hi")):
        B = cond_arrays(c, kk)
        sens.append(bands(1 - norm.cdf((B["med"] - B["err"]) / B["post_sd"])))
    p_bands[c] = {"penalized": int(pen.sum()), "eligible": int(len(pen)), **bands(A["p_above"]),
                  "ge90_k_range": sorted([s["ge90"] for s in sens]), "lt75_k_range": sorted([s["lt75"] for s in sens]),
                  "median_reliability": round(float(np.median(A["lam"])), 3)}
    print(f"  {c}: {p_bands[c]}")

# ----------------------------------------------------- persistence check ----
print("FY2023 vs FY2026 persistence, against the reliability-only ceiling")
persist = {}
for c in ["HF", "AMI", "COPD", "CABG", "THA"]:
    pts = []
    for ccn in CCNS:
        if ccn not in f23 or c not in f23[ccn]["c"]:
            continue
        a, b = f23[ccn]["c"][c], f26[ccn]["c"][c]
        if a["err"] and b["err"] and a["n"] and b["n"] and a["n"] >= MIN_N and b["n"] >= MIN_N:
            pts.append((ccn, a["n"], b["n"], a["err"], b["err"], a["pen"], b["pen"]))
    n1 = np.array([p[1] for p in pts], int); n2 = np.array([p[2] for p in pts], int)
    e1 = np.array([p[3] for p in pts]); e2 = np.array([p[4] for p in pts])
    p1 = np.array([p[5] for p in pts]); p2 = np.array([p[6] for p in pts])
    r = float(np.corrcoef(e1, e2)[0, 1])
    z, se = math.atanh(r), 1 / math.sqrt(len(pts) - 3)
    r_ci = [math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)]
    pp, pn = float(p2[p1].mean()), float(p2[~p1].mean())
    # Expected rates for the simulation: FY2026 published expected rate (FY2023's are not in the file);
    # hospitals without one get the condition's median.
    Emed = float(np.median(ARR[c]["E"]))
    E = np.array([(prov.get((p[0], c)) or {}).get("E") or Emed * 100 for p in pts]) / 100
    pg1 = np.array([f23[p[0]]["pg"] for p in pts]); pg2 = np.array([f26[p[0]]["pg"] for p in pts])

    def ceiling(k, reps=300, const_tau=False, k1=None, g=rng):
        """Correlation of the two windows' ERRs if every hospital's true ratio never changed.
        k1 (optional) gives FY2023 its own shrinkage and true-ratio spread; the true ratios
        are then perfectly correlated across windows rather than identical."""
        k1 = k if k1 is None else k1
        lam1, lam2 = n1 / (n1 + k1), n2 / (n2 + k)
        t1, t2 = (1 - E) / (E * k1), (1 - E) / (E * k)
        tau1 = np.sqrt(np.full_like(E, t1.mean()) if const_tau else t1)
        tau2 = np.sqrt(np.full_like(E, t2.mean()) if const_tau else t2)
        rs, pps = [], []
        for _ in range(reps):
            z = g.standard_normal(len(E))  # true ratio, identical in both windows when k1 == k
            q1, q2 = np.clip(E * (1 + tau1 * z), 0, 1), np.clip(E * (1 + tau2 * z), 0, 1)
            s1 = shrink(g.binomial(n1, q1), n1, E, lam1)
            s2 = shrink(g.binomial(n2, q2), n2, E, lam2)
            rs.append(np.corrcoef(s1, s2)[0, 1])
            a1, a2 = s1 > peer_medians(s1, pg1), s2 > peer_medians(s2, pg2)
            pps.append(a2[a1].mean())
        return float(np.mean(rs)), np.percentile(rs, [2.5, 97.5]).tolist(), float(np.mean(pps))
    ceil, ceil_ci, pp_stable = ceiling(kval(c))
    ends = [ceiling(kval(c, "k_lo"), 100)[0], ceiling(kval(c, "k_hi"), 100)[0]]
    ceil_const = ceiling(kval(c), 100, const_tau=True)[0]
    # Model check: the spread of FY2023 ERRs that the same k predicts vs what CMS published
    def sd23(k):
        return float(np.sqrt(np.mean((n1 / (n1 + k)) * (1 - E) / (E * k))))
    sd23_model = sd23(kval(c))
    # Per-window sensitivity: the k that makes the model match FY2023's published ERR spread,
    # and the ceiling with FY2023 shrunk by that k (separate random stream, so the main numbers don't move)
    k23 = float(brentq(lambda k: sd23(k) - float(e1.std()), 5, 1e5))
    ceil23 = ceiling(kval(c), 300, k1=k23, g=np.random.default_rng(SEED + 23))[0]
    # Observed r = rho x ceiling, where rho is the correlation of true ratios across the windows
    rho = r / ceil
    persist[c] = {"n": len(pts), "r": round(r, 3), "r_ci": [round(v, 3) for v in r_ci],
                  "ceiling": round(ceil, 3), "ceiling_sim_95": [round(v, 3) for v in ceil_ci],
                  "ceiling_k_range": [round(min(ends), 3), round(max(ends), 3)],
                  "ceiling_constant_tau": round(ceil_const, 3),
                  "share_of_ceiling": round(rho, 3), "share_of_ceiling_ci": [round(v / ceil, 3) for v in r_ci],
                  "pen_given_pen": round(pp, 3), "pen_given_not": round(pn, 3), "pen_given_pen_if_stable": round(pp_stable, 3),
                  "pen_base_rate": round(float(p2.mean()), 3),
                  "sd_err23_observed": round(float(e1.std()), 4), "sd_err23_model": round(sd23_model, 4),
                  "model_fits_fy23_spread": bool(abs(e1.std() / sd23_model - 1) < 0.15),
                  "k_fy23_fit": round(k23, 1), "ceiling_fy23_k": round(ceil23, 3),
                  "share_of_ceiling_fy23_k": round(r / ceil23, 3)}
    print(f"  {c}: {persist[c]}")
# The brief's 2,396 HF pairs came from a parser that dropped discharge counts written with a
# thousands separator ("1,234"); with those hospitals kept there are 2,516 pairs.
check("HF pairs", persist["HF"]["n"], 2516, 0)
check("HF r", persist["HF"]["r"], 0.39, 0.006)
check("HF P(pen|pen before)", persist["HF"]["pen_given_pen"], 0.60, 0.006)
check("HF P(pen|not before)", persist["HF"]["pen_given_not"], 0.39, 0.006)
for c, t in dict(AMI=0.31, COPD=0.22, CABG=0.20, THA=0.21).items():
    check(f"{c} r", persist[c]["r"], t, 0.012)
# Simulated ceilings. (The brief's 0.39/0.29/0.22/0.29/0.41 were the average per-hospital
# sqrt(rel1*rel2), which understates the population correlation when reliability varies.)
for c, t in dict(HF=0.48, AMI=0.36, COPD=0.27, CABG=0.35, THA=0.48).items():
    check(f"{c} ceiling", persist[c]["ceiling"], t, 0.02)

# ------------------------------------------------------------ write out ----
print("Writing data")
pos = {c: {int(i): j for j, i in enumerate(ARR[c]["idx"])} for c in CONDS}
# Reliability n/(n+k) and posterior SD sqrt((1-E)/(E*(n+k))) are recomputed on the page from n, E and k.
COLS = ["n", "exp_rate_pct", "err", "pen", "p_above", "err23", "pen23", "n23", "err27", "pen27", "n27"]
hosp = []
for i, ccn in enumerate(CCNS):
    h = f26[ccn]
    name = state = None
    per = []
    for c in CONDS:
        d = h["c"][c]
        p = prov.get((ccn, c))
        if p and not name:
            name, state = p["name"], p["state"]
        d27 = f27.get(ccn, {}).get("c", {}).get(c)
        t27 = [d27["err"], int(d27["pen"]), int(d27["n"])] if d27 and d27["err"] is not None and d27["n"] else [None] * 3
        if d["n"] is None or d["err"] is None:
            per.append(None)
            continue
        d23 = f23.get(ccn, {}).get("c", {}).get(c)
        t23 = [d23["err"], int(d23["pen"]), int(d23["n"])] if d23 and d23["err"] is not None and d23["n"] else [None, None, None]
        j = pos[c].get(i)
        if j is None:
            per.append([int(d["n"]), round(p["E"], 1) if p and p["E"] is not None else None, d["err"], int(d["pen"]),
                        None, *t23, *t27])
        else:
            A = ARR[c]
            per.append([int(d["n"]), round(p["E"], 1), d["err"], int(d["pen"]), round(float(A["p_above"][j]), 3), *t23, *t27])
    hosp.append([ccn, tidy_name(name) if name else f"CCN {ccn}", state or "", h["pg"], h["red"], round(h["dual"], 4), *per])
named = sum(1 for x in hosp if not x[1].startswith("CCN "))
print(f"  {named} of {len(hosp)} hospitals matched to a name")

(OUT / "hospitals.json").write_text(json.dumps(
    {"conds": CONDS, "hospital_cols": ["ccn", "name", "state", "peer_group", "reduction_pct", "dual_proportion"],
     "cond_cols": COLS, "rows": hosp}, separators=(",", ":")))
(OUT / "lineup.json").write_text(json.dumps(lineup, separators=(",", ":")))

peer_med = {c: {} for c in CONDS}
for ccn in CCNS:
    for c in CONDS:
        peer_med[c][f26[ccn]["pg"]] = f26[ccn]["c"][c]["med"]

summary = {
    "built": "2026-11-11",
    "sources": {"fy2026_supplemental": FY26_ZIP, "fy2023_supplemental": FY23_ZIP, "provider_api": PDC_API,
                "provider_dataset": "https://data.cms.gov/provider-data/dataset/9n3s-kdb3", "fy2027_supplemental": FY27_ZIP},
    "windows": {"fy2026": "July 2021 to June 2024", "fy2023": "July 2018 to Nov 2019 and July 2020 to June 2021 (CMS dropped Dec 2019 to June 2020)"},
    "labels": LABEL,
    "program": {"hospitals": len(CCNS), "penalized_share": round(float(pen_share), 5), "penalized": int((red > 0).sum()),
                "median_reduction_penalized_pct": round(med_pen, 2), "share_1pct_or_more": round(float(ge1), 5),
                "at_cap": at_cap, "recompute_max_abs_diff_pct_points": round(max_diff, 4),
                "by_eligible_conditions": by_elig, "chance_world_penalized_share": round(null_pen_share, 3),
                "mean_cross_condition_r": round(mean_cross_r, 3)},
    "fy2023_hospitals": len(f23),
    "fy2027_context": {"hospitals": len(f27), "penalized": int((red27 > 0).sum()), "penalized_share": round(float((red27 > 0).mean()), 4),
                       "window": "July 2023 to June 2025", "released": "October 2026", "source": FY27_ZIP},
    "k": KFIT,
    "real_null_sd_ratio": real_null_sd,
    "lineup_outside_band": {c: [lineup["conds"][c]["outside_band_real"], lineup["conds"][c]["outside_band_null"]] for c in CONDS},
    "eligible_with_expected": {c: int(len(ARR[c]["n"])) for c in CONDS},
    "calibration": calib,
    "probability_bands": p_bands,
    "persistence": persist,
    "peer_median": peer_med,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
for f in ("hospitals.json", "lineup.json", "summary.json"):
    print(f"  {f}: {(OUT / f).stat().st_size / 1e3:.0f} KB")
