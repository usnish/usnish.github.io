"""Build the Medicare Advantage network standards data.

CMS judges whether a Medicare Advantage network is adequate by county: for each
specialty, 90% of the plan's members must live within a maximum drive time and
distance of at least one in-network provider. The limits loosen with the county
type (Large Metro, Metro, Micro, Rural, Counties with Extreme Access Considerations)
and are customized where providers don't exist within the base limits.

For every 2020 census tract, this finds the nearest provider of each specialty that
treats Medicare patients, converts the straight-line distance to driving minutes with
the calibrated model (see _viz/calibrate_drive.py), and compares that to the CMS limit
for the tract's county. Counties are summarized over residents aged 65 and older.

Providers: clinicians in the CMS Doctors and Clinicians national file, placed at the
center of their practice ZIP code; Medicare-certified acute care and critical access
hospitals (geocoded); and Medicare-certified nursing homes (CMS coordinates).

Writes data/counties.csv and data/summary.json.
Usage: python3 ma-network-standards/scripts/build_data.py   (needs numpy, scipy, openpyxl)
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import malib as M  # noqa: E402
import vizlib as V  # noqa: E402

DAC = "https://data.cms.gov/provider-data/sites/default/files/resources/52c3f098d7e56028a298fd297cb0b38d_1787091341/DAC_NationalDownloadableFile.csv"
HOSPITALS = "https://data.cms.gov/provider-data/sites/default/files/resources/893c372430d9d71a1c52737d01239d47_1785189955/Hospital_General_Information.csv"
NURSING = "https://data.cms.gov/provider-data/sites/default/files/resources/4b708f7ece9ed1ef3060686c5546ddf1_1790792149/NH_ProviderInfo_Sep2026_3.csv"
CAP_MIN = 240  # drive times are capped at 4 hours (beyond the model's calibration range)

# id, label, HSD specialty name, Doctors and Clinicians primary specialties
SPECIALTIES = [
    ("primary", "Primary care", "Primary Care", {"INTERNAL MEDICINE", "FAMILY PRACTICE", "GENERAL PRACTICE", "GERIATRIC MEDICINE"}),
    ("cardiology", "Cardiology", "Cardiology", {"CARDIOVASCULAR DISEASE (CARDIOLOGY)", "INTERVENTIONAL CARDIOLOGY",
                                                "CARDIAC ELECTROPHYSIOLOGY", "ADVANCED HEART FAILURE AND TRANSPLANT CARDIOLOGY"}),
    ("oncology", "Oncology", "Oncology - Medical, Surgical", {"HEMATOLOGY/ONCOLOGY", "MEDICAL ONCOLOGY", "SURGICAL ONCOLOGY"}),
    ("nephrology", "Nephrology", "Nephrology", {"NEPHROLOGY"}),
    ("neurology", "Neurology", "Neurology", {"NEUROLOGY"}),
    ("psychiatry", "Psychiatry", "Psychiatry", {"PSYCHIATRY", "GERIATRIC PSYCHIATRY", "NEUROPSYCHIATRY"}),
    ("endocrinology", "Endocrinology", "Endocrinology", {"ENDOCRINOLOGY"}),
    ("pulmonology", "Pulmonology", "Pulmonology", {"PULMONARY DISEASE"}),
    ("hospital", "Hospital", "Acute Inpatient Hospitals", None),
    ("snf", "Skilled nursing", "Skilled Nursing Facilities", None),
]
DESIGNATIONS = ["Large Metro", "Metro", "Micro", "Rural", "CEAC"]


def clinicians():
    """{specialty id: [(lat, lon, clinicians)]}, one point per practice ZIP code."""
    spec_of = {s: sid for sid, _, _, specs in SPECIALTIES if specs for s in specs}
    zc = V.zcta_centroids()
    seen, counts = set(), defaultdict(lambda: defaultdict(int))
    with open(V.fetch(DAC, "DAC_NationalDownloadableFile.csv", timeout=1800), newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            sid = spec_of.get(r["pri_spec"])
            z = r["ZIP Code"][:5]
            if not sid or (r["NPI"], sid, z) in seen or z not in zc:
                continue
            seen.add((r["NPI"], sid, z))
            counts[sid][z] += 1
    out = {sid: [(*zc[z], n) for z, n in zs.items()] for sid, zs in counts.items()}
    for sid, pts in out.items():
        print(f"  {sid}: {sum(p[2] for p in pts)} clinicians at {len(pts)} ZIP codes")
    return out


def hospitals():
    rows = [r for r in V.read_csv(V.fetch(HOSPITALS, "Hospital_General_Information.csv"))
            if r["Hospital Type"] in ("Acute Care Hospitals", "Critical Access Hospitals")]
    geo = V.geocode([{"id": r["Facility ID"], "street": r["Address"], "city": r["City/Town"], "state": r["State"],
                      "zip": r["ZIP Code"]} for r in rows], "hospital_geocode.json")
    pts = [(g[0], g[1], 1) for g in (geo.get(r["Facility ID"]) for r in rows) if g]
    print(f"  hospitals: {len(pts)} of {len(rows)} located")
    return pts


def nursing_homes():
    pts = [(V.num(r["Latitude"]), V.num(r["Longitude"]), 1) for r in V.read_csv(V.fetch(NURSING, "NH_ProviderInfo.csv"))]
    pts = [p for p in pts if p[0] and p[1]]
    print(f"  nursing homes: {len(pts)}")
    return pts


def main():
    minutes, model = V.drive_model()
    rucc = V.rucc()
    svi = V.svi_tracts()
    hsd = M.hsd_limits()
    fips_of = M.ssa_fips()
    # HSD keys counties by SSA code; Connecticut and Alaska codes are translated through the enrollment file
    by_fips = {}
    for ssa, c in hsd.items():
        f = fips_of.get(ssa)
        if f:
            by_fips[f] = c
    print(f"HSD counties: {len(hsd)}, matched to FIPS: {len(by_fips)}")

    tracts = [t for t in V.tract_centers() if t["pop"] > 0]
    for t in tracts:
        s = svi(t["geoid"]) or {}
        t["old"] = V.num(s.get("E_AGE65")) or 0
        t["metro"] = V.is_metro(t["county"], rucc)
    tracts = [t for t in tracts if t["old"] > 0 and t["county"] in by_fips]
    tlat, tlon = [t["lat"] for t in tracts], [t["lon"] for t in tracts]
    old = np.array([t["old"] for t in tracts])
    desig = np.array([by_fips[t["county"]]["designation"] for t in tracts])
    print(f"tracts with 65+ residents in HSD counties: {len(tracts)}, 65+ population {old.sum():,.0f}")

    # Base limit per county type = the most common limit among counties of that type
    base = {}
    for sid, _, hsd_name, _ in SPECIALTIES:
        vals = defaultdict(lambda: defaultdict(int))
        for c in by_fips.values():
            if hsd_name in c["limits"]:
                vals[c["designation"]][c["limits"][hsd_name][0]] += 1
        base[sid] = {d: max(v, key=v.get) for d, v in vals.items()}

    points = clinicians()
    points["hospital"] = hospitals()
    points["snf"] = nursing_homes()

    county = defaultdict(lambda: {"fips": None})
    summary = {"cap_minutes": CAP_MIN, "specialties": [], "designations": DESIGNATIONS,
               "drive_model": {k: model[k] for k in ("metro", "nonmetro")}, "old_pop": int(old.sum()),
               "designation_pop": {d: int(old[desig == d].sum()) for d in DESIGNATIONS}}
    for sid, label, hsd_name, _ in SPECIALTIES:
        pts = points[sid]
        km, _ = V.nearest(tlat, tlon, [p[0] for p in pts], [p[1] for p in pts])
        near = np.array([min(max(minutes(float(d), t["metro"]), 2.0), CAP_MIN) for d, t in zip(km, tracts)])
        limit = np.array([by_fips[t["county"]]["limits"].get(hsd_name, (np.nan,))[0] for t in tracts], float)
        ok = ~np.isnan(limit)
        beyond = ok & (near > limit)
        agg = defaultdict(lambda: [0.0, 0.0, 0.0, None])  # 65+ pop, pop*nearest, pop beyond, limit
        for t, n, lim, b in zip(tracts, near, limit, beyond):
            a = agg[t["county"]]
            a[0] += t["old"]
            a[1] += t["old"] * n
            a[2] += t["old"] * b
            a[3] = None if np.isnan(lim) else lim
        for c, (p, pn, pb, lim) in agg.items():
            row = county[c]
            row["fips"] = c
            row[f"{sid}_near"] = round(pn / p, 1)
            row[f"{sid}_limit"] = "" if lim is None else int(lim)
            row[f"{sid}_slack"] = "" if lim is None else round(lim - pn / p, 1)
            row[f"{sid}_pct_beyond"] = "" if lim is None else round(100 * pb / p, 1)
        by_d = []
        for d in DESIGNATIONS:
            msk = (desig == d) & ok
            if not msk.any():
                continue
            w = old[msk]
            by_d.append({"designation": d, "limit_mean": round(float((limit[msk] * w).sum() / w.sum()), 1),
                         "limit_base": base[sid].get(d),
                         "near_mean": round(float((near[msk] * w).sum() / w.sum()), 1),
                         "pct_beyond": round(100 * float(old[msk & beyond].sum() / w.sum()), 1)})
        n_prov = sum(p[2] for p in pts)
        summary["specialties"].append({
            "id": sid, "label": label, "hsd": hsd_name, "providers": int(n_prov), "points": len(pts),
            "near_mean": round(float((near[ok] * old[ok]).sum() / old[ok].sum()), 1),
            "limit_mean": round(float((limit[ok] * old[ok]).sum() / old[ok].sum()), 1),
            "pct_beyond": round(100 * float(old[beyond].sum() / old[ok].sum()), 2),
            "old_beyond": int(old[beyond].sum()),
            "base": base[sid],
            "counties_customized": sum(1 for c in by_fips.values() if hsd_name in c["limits"]
                                       and c["limits"][hsd_name][0] != base[sid].get(c["designation"])),
            "by_designation": by_d})
        print(json.dumps(summary["specialties"][-1]))

    for c, row in county.items():
        h = by_fips[c]
        row["designation"] = h["designation"]
    cols = ["fips", "designation"] + [f"{sid}_{k}" for sid, *_ in SPECIALTIES for k in ("limit", "near", "slack", "pct_beyond")]
    (ROOT / "data").mkdir(exist_ok=True)
    V.write_csv(ROOT / "data" / "counties.csv", [county[c] for c in sorted(county)], cols)
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")


if __name__ == "__main__":
    main()
