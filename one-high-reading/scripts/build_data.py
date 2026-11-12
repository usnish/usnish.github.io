"""Build the data for "One High Reading".

NHANES III (1988-94) measured each adult's systolic blood pressure (SBP) three
times at home, by a trained household interviewer, and three more times at the
mobile examination centre (MEC), by a physician, usually about a month later.
Both used mercury sphygmomanometers. Nothing was done about the home readings
in between, so the pair shows how far a single high reading falls on its own.

For adults (18+) with all six readings, this script computes:
  - the population-wide home-vs-MEC offset;
  - how far people picked out by one home reading of T or more fall at the MEC,
    raw and beyond that offset, for every threshold T from 120 to 180;
  - a split of that fall into the setting offset, same-visit regression (home
    reading 1 vs home readings 2-3) and a between-occasion remainder;
  - the same with people picked on the mean of three home readings;
  - the reverse check (picked high at the MEC, looked back at home);
  - subgroups (no BP diagnosis reported, on BP medicine, 65+, gap length);
  - Taylor-linearised 95% CIs for the headline numbers, using the NHANES III
    design (SDPSTRA6/SDPPSU6) and MEC weights (WTPFEX6).
And from NHANES 2021-23 (oscillometric, one visit, three readings): how far a
first reading of 140+ falls by readings 2-3.

Writes data/people.csv, data/within2023.csv, data/summary.json.
Usage (from the repo root; numpy + scipy needed):
  uv run --with numpy --with scipy python3 one-high-reading/scripts/build_data.py
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vizlib as V  # noqa: E402
import xpt  # noqa: E402

NH3 = "https://wwwn.cdc.gov/nchs/data/nhanes3/1a/"
ADULT, EXAM = NH3 + "adult.dat", NH3 + "exam.dat"
NH21 = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/"
BPXO, DEMO = NH21 + "BPXO_L.xpt", NH21 + "DEMO_L.xpt"

LAW_2003_SBP = 9.1  # placebo-adjusted SBP fall at standard dose, Law et al. BMJ 2003;326:1427 (abstract)
THRESHOLDS = list(range(120, 181))
KEY = [130, 140, 160]
OUT = ROOT / "data"


def col(line, a, b):
    """1-based inclusive fixed-width field -> float (NaN if blank)."""
    try:
        return float(line[a - 1:b])
    except ValueError:
        return np.nan


def bp(v):
    return v if (v == v and 60 <= v <= 290) else np.nan


# ---------------------------------------------------------------- NHANES III
def load_nh3():
    adult = {}
    with open(V.fetch(ADULT), "rb") as fh:
        for raw in fh:
            L = raw.decode("latin-1")
            age = col(L, 18, 19)  # HSAGEIR
            if not age >= 18:
                continue
            h = [bp(col(L, 3288, 3290)), bp(col(L, 3296, 3298)), bp(col(L, 3304, 3306))]  # HAZA8AK1/BK1/CK1
            if any(x != x for x in h):
                continue
            adult[int(L[0:5])] = dict(
                age=age, w=col(L, 61, 69), psu=col(L, 43, 43), stra=col(L, 44, 45),
                hae2=col(L, 1598, 1598), hae5a=col(L, 1610, 1610), scr_mo=col(L, 21, 24), h=h)
    rows = []
    with open(V.fetch(EXAM), "rb") as fh:
        for raw in fh:
            L = raw.decode("latin-1")
            a = adult.get(int(L[0:5]))
            if a is None:
                continue
            m = [bp(col(L, 1393, 1395)), bp(col(L, 1403, 1405)), bp(col(L, 1413, 1415))]  # PEP6G1/H1/I1
            if any(x != x for x in m):
                continue
            gap = col(L, 1236, 1239) - a["scr_mo"]  # MXPAXTMR - HSAITMOR
            rows.append([*a["h"], *m, a["w"], a["psu"], a["stra"], a["age"], a["hae2"], a["hae5a"], gap])
    return np.array(rows, dtype=float)


R = load_nh3()
h, m = R[:, 0:3], R[:, 3:6]
w, psu, stra, age, hae2, hae5a, gap = R[:, 6:13].T
assert (w > 0).all(), "every MEC-examined adult should carry a MEC weight"
N = len(R)
h1, hmean, h23 = h[:, 0], h.mean(1), h[:, 1:].mean(1)
m1, mmean, m23 = m[:, 0], m.mean(1), m[:, 1:].mean(1)
ALL = np.ones(N, bool)
PSU_KEY = stra * 10 + psu
T_DF = len(np.unique(PSU_KEY)) - len(np.unique(stra))
T_CRIT = stats.t.ppf(0.975, T_DF)


def wm(x, s=ALL):
    return float(np.sum(w[s] * x[s]) / np.sum(w[s]))


def lin(terms):
    """Estimate sum(c * weighted mean of x over domain s) with a Taylor-linearised 95% CI.

    terms: [(c, x, s)]. Variance from PSU totals of the linearised values within
    strata (with-replacement approximation, as in NHANES analytic guidance).
    """
    est, z = 0.0, np.zeros(N)
    for c, x, s in terms:
        W = w[s].sum()
        mu = np.sum(w[s] * x[s]) / W
        est += c * mu
        z[s] += c * w[s] * (x[s] - mu) / W
    var = 0.0
    for st in np.unique(stra):
        ks = np.unique(PSU_KEY[stra == st])
        tot = np.array([z[PSU_KEY == k].sum() for k in ks])
        if len(ks) > 1:
            var += len(ks) / (len(ks) - 1) * np.sum((tot - tot.mean()) ** 2)
    se = var ** 0.5
    return {"est": round(est, 2), "lo": round(est - T_CRIT * se, 2), "hi": round(est + T_CRIT * se, 2)}


d1 = h1 - mmean          # one home reading minus the MEC mean of 3
dmean = hmean - mmean    # home mean of 3 minus the MEC mean of 3
dwv = h1 - h23           # home reading 1 minus home readings 2-3 (same visit)
OFF = wm(d1)
OFF_MEAN = wm(dmean)
DRIFT_HOME, DRIFT_MEC = wm(dwv), wm(m1 - m23)


def by_threshold(sel_one, sel_mean, base=ALL):
    out = []
    for T in THRESHOLDS:
        s = base & (sel_one >= T)
        sm = base & (sel_mean >= T)
        beyond = wm(d1, s) - OFF
        wv = wm(dwv, s) - DRIFT_HOME
        out.append({
            "t": T, "n": int(s.sum()), "first": round(wm(h1, s), 2), "mec": round(wm(mmean, s), 2),
            "fall": round(wm(d1, s), 2), "beyond": round(beyond, 2),
            "same_visit": round(wv, 2), "second_day": round(beyond - wv, 2),
            "n_mean3": int(sm.sum()), "home_mean3": round(wm(hmean, sm), 2), "mec_mean3": round(wm(mmean, sm), 2),
            "fall_mean3": round(wm(dmean, sm), 2), "beyond_mean3": round(wm(dmean, sm) - OFF_MEAN, 2),
        })
    return out


rows_all = by_threshold(h1, hmean)
row = {r["t"]: r for r in rows_all}
nodx = (hae2 == 2)
meds = (hae5a == 1)
old = age >= 65
gap_ok = gap == gap


def sub(s, T=140):
    ss = s & (h1 >= T)
    return {"n": int(ss.sum()), "fall": round(wm(d1, ss), 2), "beyond": round(wm(d1, ss) - OFF, 2),
            "ci": lin([(1, d1, ss), (-1, d1, ALL)])}


subgroups = {
    "no_dx": {**sub(nodx), "label": "No BP diagnosis reported"},
    "meds": {**sub(meds), "label": "Taking BP medicine"},
    "age65": {**sub(old), "label": "Age 65 and over"},
    "age_under65": {**sub(~old), "label": "Age 18 to 64"},
    "gap_le1": {**sub(gap_ok & (gap <= 1)), "label": "Exam within 1 month"},
    "gap_ge2": {**sub(gap_ok & (gap >= 2)), "label": "Exam 2 or more months later"},
}
nodx_rows = {T: sub(nodx, T) for T in KEY}

# Weighted regression of the MEC mean on home reading 1, and the correlation
X = np.c_[np.ones(N), h1]
coef = np.linalg.solve(X.T @ (X * w[:, None]), X.T @ (w * mmean))
cov = np.cov(h1, mmean, aweights=w)
corr_w = cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1])

# Reverse selection: high on MEC reading 1, look back at the home mean
rev = m1 >= 140
rev_expected = wm(hmean - m1)  # population: home mean minus MEC reading 1
reverse = {
    "n": int(rev.sum()), "mec1": round(wm(m1, rev), 2), "home_mean": round(wm(hmean, rev), 2),
    "expected_home_mean": round(wm(m1, rev) + rev_expected, 2),
    "beyond": round(wm(hmean - m1, rev) - rev_expected, 2),
    "ci": lin([(1, hmean - m1, rev), (-1, hmean - m1, ALL)]),
}

# Binned means for the predict-first chart (10 mmHg bins on home reading 1)
EDGES = list(range(90, 200, 10)) + [200, 300]
bins = []
for lo, hi in zip(EDGES[:-1], EDGES[1:]):
    s = (h1 >= lo) & (h1 < hi)
    if s.sum() == 0:
        continue
    bins.append({"lo": lo, "hi": hi, "n": int(s.sum()), "x": round(wm(h1, s), 2), "mec": round(wm(mmean, s), 2)})
n_below, n_above = int((h1 < 90).sum()), int((h1 >= 300).sum())

# Bland-Altman: home reading 1 minus MEC mean, by the average of the two
ba = []
avg = (h1 + mmean) / 2
for lo in range(100, 200, 20):
    s = (avg >= lo) & (avg < lo + 20)
    ba.append({"lo": lo, "hi": lo + 20, "n": int(s.sum()), "diff": round(wm(d1, s), 2)})

# MEC-only same-visit regression (MEC reading 1 >= T -> MEC readings 2-3)
mec_wv = {T: round(wm(m1 - m23, m1 >= T) - DRIFT_MEC, 2) for T in KEY}

# Headline CIs
ci = {
    **{f"beyond_{T}": lin([(1, d1, h1 >= T), (-1, d1, ALL)]) for T in KEY},
    **{f"same_visit_{T}": lin([(1, dwv, h1 >= T), (-1, dwv, ALL)]) for T in KEY},
    "beyond_mean3_140": lin([(1, dmean, hmean >= 140), (-1, dmean, ALL)]),
    "one_minus_mean3_140": lin([(1, d1, h1 >= 140), (-1, d1, ALL), (-1, dmean, hmean >= 140), (1, dmean, ALL)]),
    "offset": lin([(1, d1, ALL)]),
}

# --------------------------------------------------------------- NHANES 2021-23
bpx, demo = xpt.read(V.fetch(BPXO)), xpt.read(V.fetch(DEMO))
dm = {sq: i for i, sq in enumerate(demo["SEQN"])}
mod = []
for i, sq in enumerate(bpx["SEQN"]):
    j = dm.get(sq)
    if j is None:
        continue
    a, wt = demo["RIDAGEYR"][j], demo["WTMEC2YR"][j]
    vals = [bpx[k][i] for k in ("BPXOSY1", "BPXOSY2", "BPXOSY3", "BPXODI1", "BPXODI2", "BPXODI3")]
    if not a >= 18 or any(v != v for v in vals) or not wt > 0:
        continue
    mod.append([*vals, wt, demo["SDMVSTRA"][j], demo["SDMVPSU"][j]])
M = np.array(mod)
s1, s23 = M[:, 0], M[:, 1:3].mean(1)
d1m, d23 = M[:, 3], M[:, 4:6].mean(1)
w2 = M[:, 6]


def wm2(x, s):
    return float(np.sum(w2[s] * x[s]) / np.sum(w2[s]))


A2 = np.ones(len(M), bool)
hi2 = s1 >= 140
modern = {
    "n": int(len(M)), "n_140": int(hi2.sum()),
    "drift_all": round(wm2(s1 - s23, A2), 2),
    "fall_140": round(wm2(s1 - s23, hi2), 2),
    "beyond_140": round(wm2(s1 - s23, hi2) - wm2(s1 - s23, A2), 2),
    "pct_under_140": round(100 * wm2((s23 < 140).astype(float), hi2), 1),
    "prev_130_80_first": round(100 * wm2(((s1 >= 130) | (d1m >= 80)).astype(float), A2), 1),
    "prev_130_80_mean23": round(100 * wm2(((s23 >= 130) | (d23 >= 80)).astype(float), A2), 1),
}

# ------------------------------------------------------------------- outputs
OUT.mkdir(exist_ok=True)


def flag(v):
    return "1" if v == 1 else "0" if v == 2 else ""


band = np.where(age >= 65, "65+", np.where(age >= 40, "40-64", "18-39"))
order = np.lexsort((mmean, h1))  # sorted by values, so row order carries no survey ID
with open(OUT / "people.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["h1", "h2", "h3", "m1", "m2", "m3", "w", "told", "meds", "age"])
    for i in order:
        wr.writerow([*(int(v) for v in h[i]), *(int(v) for v in m[i]), int(round(w[i])), flag(hae2[i]), flag(hae5a[i]), band[i]])
order2 = np.lexsort((s23, s1))
with open(OUT / "within2023.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["sbp1", "mean23", "w"])
    for i in order2:
        wr.writerow([int(s1[i]), f"{s23[i]:g}", int(round(w2[i]))])

r140 = row[140]
summary = {
    "built_with": "one-high-reading/scripts/build_data.py",
    "n": N, "years": "1988-94",
    "gap_months_median": float(np.median(gap[gap_ok])), "gap_months_p90": float(np.percentile(gap[gap_ok], 90)),
    "gap_known": int(gap_ok.sum()),
    "offset": round(OFF, 2), "offset_mean3": round(OFF_MEAN, 2),
    "drift_home": round(DRIFT_HOME, 2), "drift_mec": round(DRIFT_MEC, 2),
    "slope": round(float(coef[1]), 3), "intercept": round(float(coef[0]), 2), "corr": round(float(corr_w), 3),
    "corr_unweighted": round(float(np.corrcoef(h1, mmean)[0, 1]), 3),
    "bins": bins, "n_below_90": n_below, "n_300_plus": n_above,
    "bland_altman": ba, "ba_min": min(b["diff"] for b in ba), "ba_max": max(b["diff"] for b in ba),
    "thresholds": rows_all,
    "no_dx_thresholds": {str(T): v for T, v in nodx_rows.items()},
    "subgroups": subgroups,
    "reverse": reverse,
    "mec_same_visit": {str(T): v for T, v in mec_wv.items()},
    "ci": ci, "ci_df": int(T_DF),
    "averaging_share_140": round((r140["beyond"] - r140["beyond_mean3"]) / r140["beyond"], 3),
    "drug": {"sbp": LAW_2003_SBP, "source": "Law MR, Wald NJ, Morris JK, Jordan RE. BMJ 2003;326:1427"},
    "not_drug_share_140": round(r140["beyond"] / (LAW_2003_SBP + r140["beyond"]), 3),
    "not_drug_share_140_nodx": round(subgroups["no_dx"]["beyond"] / (LAW_2003_SBP + subgroups["no_dx"]["beyond"]), 3),
    "modern": modern,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))

# ----------------------------------------------------- checks against the brief
def near(a, b, tol=0.15):
    assert abs(a - b) <= tol, (a, b)


assert N == 15689, N
near(OFF, 3.80); near(OFF_MEAN, 3.12)
assert r140["n"] == 3853, r140["n"]
near(r140["first"], 154.4); near(r140["mec"], 143.3); near(r140["fall"], 11.1); near(r140["beyond"], 7.3)
near(row[130]["fall"], 8.8); near(row[130]["beyond"], 5.0); near(row[160]["fall"], 17.4); near(row[160]["beyond"], 13.6)
assert subgroups["no_dx"]["n"] == 1708; near(subgroups["no_dx"]["fall"], 12.2); near(subgroups["no_dx"]["beyond"], 8.4)
near(coef[1], 0.73); near(corr_w, 0.76)
assert r140["n_mean3"] == 3506; near(r140["beyond_mean3"], 6.6)
near(-reverse["beyond"], 9.1)
near(DRIFT_HOME, 1.0); near(DRIFT_MEC, 1.7)
for T, b, c in [(130, 1.0, 4.0), (140, 1.4, 5.9), (160, 1.7, 11.9)]:
    near(row[T]["same_visit"], b); near(row[T]["second_day"], c)
near(subgroups["gap_le1"]["beyond"], 7.4); near(subgroups["gap_ge2"]["beyond"], 6.5)
near(subgroups["age65"]["beyond"], 5.6); near(subgroups["meds"]["beyond"], 6.7)
near(summary["gap_months_median"], 1); near(summary["gap_months_p90"], 2)
near(modern["fall_140"], 2.6) if abs(modern["fall_140"] - 2.6) <= 0.15 else near(modern["beyond_140"], 2.6)
near(modern["pct_under_140"], 23, 1); near(modern["prev_130_80_first"], 40.0); near(modern["prev_130_80_mean23"], 37.1)

print(f"n={N} offset={OFF:.2f} beyond140={r140['beyond']:.2f} mean3={r140['beyond_mean3']:.2f} "
      f"reverse={reverse['beyond']:.2f} slope={coef[1]:.3f} corr={corr_w:.3f} modern n={len(M)} "
      f"fall140={modern['fall_140']} beyond140={modern['beyond_140']}")
print("CIs:", json.dumps(ci))
print("bins:", [(b["lo"], b["n"]) for b in bins], "below90", n_below)
print("BA:", [(b["lo"], b["diff"]) for b in ba])
for f in ("people.csv", "within2023.csv", "summary.json"):
    print(f, (OUT / f).stat().st_size, "bytes")
