"""Build the Medicare Advantage network standards data.

CMS judges whether a Medicare Advantage network is adequate county by county. For each
specialty, CMS publishes a maximum drive time and distance (HSD Reference File) that loosens
with the county type (Large Metro, Metro, Micro, Rural, Counties with Extreme Access
Considerations) and is raised ("customized") where providers are scarce. Under
42 CFR 422.116(d)(4), a plan passes if at least 90% of the Medicare beneficiaries residing in
Large Metro and Metro counties, and at least 85% in Micro, Rural and CEAC counties, live within
those limits of an in-network provider (CMS measures this against its MA Medicare Sample Census,
not the plan's enrollees). Under 422.116(d)(5), a plan that also contracts telehealth
providers gets a 10-percentage-point credit for listed specialties (cardiology, psychiatry,
neurology, nephrology, primary care and endocrinology among the ones shown here).

For every 2020 census tract, this finds the nearest provider of each specialty that
treats Medicare patients, converts the straight-line distance to driving minutes with
the calibrated model (see _viz/calibrate_drive.py), and compares that to the CMS limit
for the tract's county. Counties are summarized over residents aged 65 and older.

Providers: clinicians in the CMS Doctors and Clinicians national file, placed at the
center of each practice ZIP code they are listed at; Medicare-certified acute care and
critical access hospitals (geocoded); and Medicare-certified nursing homes (CMS coordinates;
Medicaid-only nursing facilities are left out).

Visiting clinics: many specialists are also listed at small hospitals far from their main
practice, where they hold a clinic a few days a month. A ZIP code is treated as a visiting
site, and left out of the nearest-provider distances, when every clinician of that
specialty listed there is also listed at a ZIP code more than VISIT_KM away that has more
clinicians of the same specialty. The build also reports the rural averages with those
sites counted.

Writes data/counties.csv, data/summary.json and data/top10_check.csv (the hand check of
the top of each ranking; see check_top10()).
Usage: python3 ma-network-standards/scripts/build_data.py   (needs numpy, scipy, openpyxl)
"""
import csv
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import malib as M  # noqa: E402
import vizlib as V  # noqa: E402

# Current distribution of dataset mj5m-pzi6 (metastore "modified" 2026-10-30). The number after the
# underscore is CMS's upload time (Unix seconds); the release date shown on the page is taken from it,
# and the cache file is named by it so a new release is never mixed up with a cached old one.
DAC = "https://data.cms.gov/provider-data/sites/default/files/resources/52c3f098d7e56028a298fd297cb0b38d_1793398546/DAC_NationalDownloadableFile.csv"
DAC_STAMP = int(DAC.rsplit("/", 2)[-2].rsplit("_", 1)[-1])
DAC_CACHE = f"DAC_NationalDownloadableFile_{DAC_STAMP}.csv"
HOSPITALS = "https://data.cms.gov/provider-data/sites/default/files/resources/893c372430d9d71a1c52737d01239d47_1785189955/Hospital_General_Information.csv"
NURSING = "https://data.cms.gov/provider-data/sites/default/files/resources/4b708f7ece9ed1ef3060686c5546ddf1_1790792149/NH_ProviderInfo_Sep2026_3.csv"
PLAN_YEAR = 2026  # the HSD Reference File in malib.HSD governs contract year 2026
CAP_MIN = 240  # drive times are capped at 4 hours (beyond the model's calibration range)
VISIT_KM = 100  # a listing this far from a bigger practice of the same clinician counts as a visiting clinic

# 42 CFR 422.116(d)(4): share of the beneficiaries residing in the county who must live within the limits
MUST_WITHIN = {"Large Metro": 90, "Metro": 90, "Micro": 85, "Rural": 85, "CEAC": 85}
# 42 CFR 422.116(d)(5): 10-point telehealth credit; specialties on the list that this page shows
TELEHEALTH_CREDIT = 10
TELEHEALTH_SPECIALTIES = {"Primary Care", "Cardiology", "Psychiatry", "Neurology", "Nephrology", "Endocrinology"}

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
# Primary care limits are 10 to 40 minutes. At that range the drive model's fixed start
# (about 7-8 minutes) and ZIP-code placement decide whether a tract lands "past the limit",
# so that share is not published for primary care.
NO_BEYOND = {"primary"}


def clinicians():
    """Clinician locations by specialty.

    Returns {sid: {"regular": [(lat, lon, clinicians)], "visiting": [(lat, lon, clinicians)],
    "sites": {zip: {"n": clinicians, "regular": bool, "visitors": [(npi, [far zips])]}},
    "clinicians": unique NPIs with a mappable ZIP, "pairs": clinician-ZIP pairs}}.
    """
    spec_of = {s: sid for sid, _, _, specs in SPECIALTIES if specs for s in specs}
    zc = V.zcta_centroids()
    zips = defaultdict(lambda: defaultdict(set))  # sid -> npi -> {zip}
    with open(V.fetch(DAC, DAC_CACHE, timeout=1800), newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            sid = spec_of.get(r["pri_spec"])
            z = r["ZIP Code"][:5]
            if sid and z in zc:
                zips[sid][r["NPI"]].add(z)
    out = {}
    for sid, by_npi in zips.items():
        n_at = defaultdict(int)
        for zs in by_npi.values():
            for z in zs:
                n_at[z] += 1
        resident, visitors = defaultdict(int), defaultdict(list)
        for npi, zs in by_npi.items():
            for z in zs:
                far = [o for o in zs if n_at[o] > n_at[z] and V.haversine_km(*zc[z], *zc[o]) > VISIT_KM]
                if far:
                    visitors[z].append((npi, sorted(far, key=lambda o: -n_at[o])))
                else:
                    resident[z] += 1
        sites = {z: {"n": n, "regular": resident[z] > 0, "visitors": visitors[z]} for z, n in n_at.items()}
        out[sid] = {"regular": [(*zc[z], n) for z, n in n_at.items() if resident[z]],
                    "visiting": [(*zc[z], n) for z, n in n_at.items() if not resident[z]],
                    "regular_zips": [z for z in n_at if resident[z]],
                    "sites": sites, "clinicians": len(by_npi), "pairs": sum(n_at.values())}
        print(f"  {sid}: {len(by_npi)} clinicians, {out[sid]['pairs']} clinician-ZIP listings at {len(n_at)} ZIP codes, "
              f"{len(out[sid]['visiting'])} of them visiting sites only")
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
    # Medicaid-only nursing facilities are not Medicare SNFs, so they cannot be in an MA SNF network
    rows = V.read_csv(V.fetch(NURSING, "NH_ProviderInfo.csv"))
    snf = [r for r in rows if r["Provider Type"] != "Medicaid"]
    pts = [(V.num(r["Latitude"]), V.num(r["Longitude"]), 1) for r in snf]
    pts = [p for p in pts if p[0] and p[1]]
    print(f"  nursing homes: {len(pts)} located, of {len(snf)} Medicare-certified ({len(rows) - len(snf)} Medicaid-only left out)")
    return pts


def drive(minutes, km, tracts):
    return np.array([min(max(minutes(float(d), t["metro"]), 2.0), CAP_MIN) for d, t in zip(km, tracts)])


def wmean(x, w):
    return round(float((x * w).sum() / w.sum()), 1)


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

    clin = clinicians()
    points = {sid: c["regular"] for sid, c in clin.items()}
    points["hospital"] = hospitals()
    points["snf"] = nursing_homes()

    county = defaultdict(lambda: {"fips": None})
    nearest_site = {}  # sid -> per-tract nearest regular ZIP (clinicians only), for the top-10 check
    near_by_sid = {}
    dac_date = datetime.date.fromtimestamp((V.CACHE / DAC_CACHE).stat().st_mtime)
    dac_release = datetime.datetime.fromtimestamp(DAC_STAMP, datetime.timezone.utc).date()
    ceac_states = defaultdict(int)  # where the "extreme access" counties are
    for c in by_fips.values():
        if c["designation"] == "CEAC":
            ceac_states[c["st"]] += 1
    summary = {"plan_year": PLAN_YEAR, "hsd_file": M.HSD.rsplit("/", 1)[-1], "cap_minutes": CAP_MIN,
               "clinicians_downloaded": dac_date.strftime("%B %Y"),
               "clinicians_release": f"{dac_release:%B} {dac_release.day}, {dac_release.year}",
               "ceac_counties": sum(ceac_states.values()),
               "ceac_top_states": sorted(ceac_states.items(), key=lambda kv: -kv[1])[:8],
               "alaska_ceac": [ceac_states["AK"], sum(1 for c in by_fips.values() if c["st"] == "AK")],
               "visit_km": VISIT_KM, "telehealth_credit": TELEHEALTH_CREDIT, "must_within": MUST_WITHIN,
               "specialties": [], "designations": DESIGNATIONS,
               "drive_model": {k: model[k] for k in ("metro", "nonmetro")}, "old_pop": int(old.sum()),
               "designation_pop": {d: int(old[desig == d].sum()) for d in DESIGNATIONS}}
    for sid, label, hsd_name, specs in SPECIALTIES:
        pts = points[sid]
        km, idx = V.nearest(tlat, tlon, [p[0] for p in pts], [p[1] for p in pts])
        near = drive(minutes, km, tracts)
        near_by_sid[sid] = near
        near_all = near
        if specs:
            nearest_site[sid] = [clin[sid]["regular_zips"][i] for i in idx]
            every = pts + clin[sid]["visiting"]
            km_all, _ = V.nearest(tlat, tlon, [p[0] for p in every], [p[1] for p in every])
            near_all = drive(minutes, km_all, tracts)
        limit = np.array([by_fips[t["county"]]["limits"].get(hsd_name, (np.nan,))[0] for t in tracts], float)
        ok = ~np.isnan(limit)
        beyond = ok & (near > limit)
        show_beyond = sid not in NO_BEYOND
        credit = TELEHEALTH_CREDIT if hsd_name in TELEHEALTH_SPECIALTIES else 0
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
            row[f"{sid}_pct_beyond"] = "" if lim is None or not show_beyond else round(100 * pb / p, 1)
        by_d = []
        for d in DESIGNATIONS:
            msk = (desig == d) & ok
            if not msk.any():
                continue
            w = old[msk]
            at_base = msk & (limit == base[sid].get(d))
            by_d.append({"designation": d, "limit_mean": wmean(limit[msk], w),
                         "limit_base": base[sid].get(d),
                         "base_share": round(100 * float(old[at_base].sum() / w.sum()), 1),
                         "must_within": MUST_WITHIN[d], "may_beyond": 100 - MUST_WITHIN[d] + credit,
                         "near_mean": wmean(near[msk], w),
                         "slack_mean": wmean(limit[msk] - near[msk], w),
                         "near_mean_with_visiting": wmean(near_all[msk], w),
                         "pct_beyond": round(100 * float(old[msk & beyond].sum() / w.sum()), 1) if show_beyond else None})
        entry = {"id": sid, "label": label, "hsd": hsd_name, "telehealth_credit": credit,
                 "show_beyond": show_beyond,
                 "near_mean": wmean(near[ok], old[ok]),
                 "limit_mean": wmean(limit[ok], old[ok]),
                 "pct_beyond": round(100 * float(old[beyond].sum() / old[ok].sum()), 2) if show_beyond else None,
                 "old_beyond": int(old[beyond].sum()) if show_beyond else None,
                 "base": base[sid],
                 "counties_customized": sum(1 for c in by_fips.values() if hsd_name in c["limits"]
                                            and c["limits"][hsd_name][0] != base[sid].get(c["designation"])),
                 "by_designation": by_d}
        if specs:
            entry.update({"kind": "clinicians", "clinicians": clin[sid]["clinicians"], "listings": clin[sid]["pairs"],
                          "sites": len(clin[sid]["regular"]), "visiting_sites": len(clin[sid]["visiting"])})
        else:
            entry.update({"kind": "facilities", "facilities": len(pts)})
        summary["specialties"].append(entry)
        print(json.dumps(entry))

    for c, row in county.items():
        row["designation"] = by_fips[c]["designation"]
    cols = ["fips", "designation"] + [f"{sid}_{k}" for sid, *_ in SPECIALTIES for k in ("limit", "near", "slack", "pct_beyond")]
    (ROOT / "data").mkdir(exist_ok=True)
    V.write_csv(ROOT / "data" / "counties.csv", [county[c] for c in sorted(county)], cols)
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    check_top10(county, by_fips, tracts, clin, nearest_site, near_by_sid)


def check_top10(county, by_fips, tracts, clin, nearest_site, near_by_sid):
    """The top 10 counties of each cardiology ranking (as the page lists them: Alaska left out),
    with the site the county's largest 65+ tract is routed to, whether that site was also a
    visiting site for some clinicians, and a real driving time for that trip from the public
    OSRM router to compare with the model. Writes data/top10_check.csv."""
    sid = "cardiology"
    zc = V.zcta_centroids()
    big = {}
    for i, t in enumerate(tracts):
        if t["county"] not in big or t["old"] > tracts[big[t["county"]]]["old"]:
            big[t["county"]] = i
    rows = []
    cache = V.CACHE / "ma-network" / "osrm_top10.json"  # routes are cached so rebuilds don't re-query OSRM
    cache.parent.mkdir(parents=True, exist_ok=True)
    routed = json.loads(cache.read_text()) if cache.exists() else {}
    for meas in ("slack", "limit", "near", "pct_beyond"):
        cand = [r for r in county.values() if r["fips"][:2] != "02" and r[f"{sid}_{meas}"] != ""]
        for rank, r in enumerate(sorted(cand, key=lambda r: -r[f"{sid}_{meas}"])[:10], 1):
            i = big[r["fips"]]
            t, z = tracts[i], nearest_site[sid][i]
            site = clin[sid]["sites"][z]
            k = f"{t['geoid']}>{z}"
            if k not in routed:
                routed[k] = V.osrm_minutes(t["lat"], t["lon"], *zc[z])
            osrm = routed[k]
            rows.append({"ranking": meas, "rank": rank, "fips": r["fips"], "county": by_fips[r["fips"]]["county"],
                         "st": by_fips[r["fips"]]["st"], "designation": r["designation"], "value": r[f"{sid}_{meas}"],
                         "largest_tract": t["geoid"], "nearest_zip": z, "cardiologists_at_zip": site["n"],
                         "also_visiting_site_for": len(site["visitors"]),
                         "model_minutes": round(float(near_by_sid[sid][i]), 1),
                         "osrm_minutes": "" if osrm is None else round(osrm, 1)})
    cache.write_text(json.dumps(routed))
    V.write_csv(ROOT / "data" / "top10_check.csv", rows, list(rows[0]))
    print(f"top-10 check: {len(rows)} rows, {len(routed)} routes")


if __name__ == "__main__":
    main()
