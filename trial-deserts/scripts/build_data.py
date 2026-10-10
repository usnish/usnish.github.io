"""Build the clinical trial deserts data.

For four common chronic conditions, pull every interventional study on
ClinicalTrials.gov that is recruiting at a U.S. site, find the nearest recruiting
site to every 2020 census tract, convert the straight-line distance to estimated
driving minutes (see _viz/calibrate_drive.py), and summarize who lives more than
an hour away: by county, by race and ethnicity, by social vulnerability, and by
metro vs. nonmetro. Disease burden comes from CDC PLACES county estimates.

Writes data/counties.csv, data/sites.csv, data/summary.json.
Usage: python3 trial-deserts/scripts/build_data.py   (needs numpy, scipy)
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
PLACES = {"2025": "https://data.cdc.gov/resource/swc5-untb.json", "2024": "https://data.cdc.gov/resource/fu4u-a9bh.json"}
FAR_MIN = 60
CAP_MIN = 240  # beyond ~4 hours (mostly Alaska and the rural West) the trip is impractical and the linear model unreliable
CONDITIONS = [
    # id, ClinicalTrials.gov condition search, PLACES measure, label
    ("diabetes", "type 2 diabetes", "DIABETES", "Type 2 diabetes"),
    ("chd", "coronary artery disease", "CHD", "Coronary heart disease"),
    ("cancer", "cancer", "CANCER", "Cancer"),
    ("copd", "COPD", "COPD", "COPD"),
]
GROUPS = [  # SVI 2022 race/ethnicity estimates; "White" = total minus minority
    ("white", "White, non-Hispanic"), ("afam", "Black"), ("hisp", "Hispanic or Latino"),
    ("asian", "Asian"), ("aian", "American Indian / Alaska Native"),
]


def studies(cond):
    """Recruiting interventional studies with U.S. sites -> list of studies."""
    out, token = [], None
    while True:
        params = {"query.cond": cond, "filter.overallStatus": "RECRUITING", "query.locn": "United States",
                  "filter.advanced": "AREA[StudyType]INTERVENTIONAL", "pageSize": 1000,
                  "fields": "NCTId,BriefTitle,Phase,LeadSponsorName,LocationFacility,LocationCity,LocationState,"
                            "LocationCountry,LocationStatus,LocationGeoPoint"}
        if token:
            params["pageToken"] = token
        j = V.get_json(CTGOV, params)
        out += j.get("studies", [])
        token = j.get("nextPageToken")
        if not token:
            return out
        time.sleep(0.5)


def sites_for(cond):
    """Unique recruiting U.S. site locations with the number of trials at each."""
    pts = defaultdict(lambda: {"trials": set()})
    st = studies(cond)
    for s in st:
        nct = s["protocolSection"]["identificationModule"]["nctId"]
        for loc in s["protocolSection"].get("contactsLocationsModule", {}).get("locations", []):
            gp = loc.get("geoPoint")
            if loc.get("country") != "United States" or loc.get("status") != "RECRUITING" or not gp:
                continue
            key = (round(gp["lat"], 3), round(gp["lon"], 3))
            p = pts[key]
            p["lat"], p["lon"] = key
            p["city"], p["state"] = loc.get("city", ""), loc.get("state", "")
            p["trials"].add(nct)
    return st, [{**p, "trials": len(p["trials"])} for p in pts.values()]


def places(measure):
    """County crude prevalence + adult population; KY/PA from the 2024 release (absent in 2025)."""
    out = {}
    for rel in ("2024", "2025"):  # 2025 overwrites wherever it has data
        for r in V.get_json(PLACES[rel], {"measureid": measure, "datavaluetypeid": "CrdPrv", "$limit": 5000}):
            if len(r.get("locationid", "")) == 5 and r.get("data_value"):
                out[r["locationid"]] = (float(r["data_value"]), int(r["totalpop18plus"]), r["year"])
    return out


def main():
    minutes, model = V.drive_model()
    rucc = V.rucc()
    svi = V.svi_tracts()
    tracts = [t for t in V.tract_centers() if t["pop"] > 0]
    for t in tracts:
        s = svi(t["geoid"]) or {}
        tot = V.num(s.get("E_TOTPOP")) or 0
        t["svi"] = V.num(s.get("RPL_THEMES"))
        t["metro"] = V.is_metro(t["county"], rucc)
        # scale ACS race counts to the 2020 tract population used for weights
        f = t["pop"] / tot if tot else 0
        t["afam"] = (V.num(s.get("E_AFAM")) or 0) * f
        t["hisp"] = (V.num(s.get("E_HISP")) or 0) * f
        t["asian"] = (V.num(s.get("E_ASIAN")) or 0) * f
        t["aian"] = (V.num(s.get("E_AIAN")) or 0) * f
        t["white"] = max(tot - (V.num(s.get("E_MINRTY")) or 0), 0) * f
    tlat, tlon = [t["lat"] for t in tracts], [t["lon"] for t in tracts]
    pop = np.array([t["pop"] for t in tracts], float)

    county_rows = defaultdict(dict)
    summary = {"far_minutes": FAR_MIN, "cap_minutes": CAP_MIN, "conditions": [], "date": time.strftime("%Y-%m-%d"),
               "drive_model": {k: model[k] for k in ("metro", "nonmetro")}}
    all_sites = []
    for cid, query, measure, label in CONDITIONS:
        st, sites = sites_for(query)
        km, idx = V.nearest(tlat, tlon, [s["lat"] for s in sites], [s["lon"] for s in sites])
        mins = np.array([min(max(minutes(float(d), t["metro"]), 2.0), CAP_MIN) for d, t in zip(km, tracts)])
        far = mins > FAR_MIN

        prev = places(measure)
        # CT counties: PLACES reports planning regions, so use the adult-weighted state rate
        ct = [v for k, v in prev.items() if k.startswith("09") and k >= "09100"]
        ct_rate = sum(p * n for p, n, _ in ct) / sum(n for _, n, _ in ct) if ct else None

        agg = defaultdict(lambda: [0.0, 0.0, 0.0])  # pop, pop*min, far pop
        for t, m, f in zip(tracts, mins, far):
            a = agg[t["county"]]
            a[0] += t["pop"]
            a[1] += t["pop"] * m
            a[2] += t["pop"] * f
        burden_total = burden_far = 0.0
        for c, (p, pm, fp) in agg.items():
            row = county_rows[c]
            row["fips"] = c
            row[f"{cid}_min"] = round(pm / p, 1)
            row[f"{cid}_pct_far"] = round(100 * fp / p, 1)
            rate, adults = (prev[c][0], prev[c][1]) if c in prev else (ct_rate, None) if c.startswith("09") else (None, None)
            if rate is not None:
                adults = adults or p * 0.78  # CT: 2020 population x national adult share
                patients = rate / 100 * adults
                row[f"{cid}_prev"] = round(rate, 1)
                row[f"{cid}_patients_far"] = round(patients * fp / p)
                burden_total += patients
                burden_far += patients * fp / p

        by_group = {}
        for g, glabel in GROUPS:
            w = np.array([t[g] for t in tracts])
            by_group[glabel] = round(100 * float(w[far].sum() / w.sum()), 1)
        by_svi = {}
        sv = np.array([t["svi"] if t["svi"] is not None else -1 for t in tracts])
        for q, lo, hi in [("Least vulnerable quarter", 0, .25), ("2nd", .25, .5), ("3rd", .5, .75), ("Most vulnerable quarter", .75, 1.01)]:
            msk = (sv >= lo) & (sv < hi)
            by_svi[q] = round(100 * float(pop[msk & far].sum() / pop[msk].sum()), 1)
        metro = np.array([t["metro"] for t in tracts])
        summary["conditions"].append({
            "id": cid, "label": label, "query": query, "places_measure": measure,
            "studies": len(st), "sites": len(sites),
            "pct_pop_far": round(100 * float(pop[far].sum() / pop.sum()), 1),
            "pct_patients_far": round(100 * burden_far / burden_total, 1),
            "patients_far": round(burden_far),
            "pct_far_by_group": by_group, "pct_far_by_svi": by_svi,
            "pct_far_metro": round(100 * float(pop[metro & far].sum() / pop[metro].sum()), 1),
            "pct_far_nonmetro": round(100 * float(pop[~metro & far].sum() / pop[~metro].sum()), 1),
        })
        all_sites += [{"condition": cid, **s} for s in sites]
        print(json.dumps(summary["conditions"][-1]))

    cols = ["fips"] + [f"{c}_{k}" for c, *_ in CONDITIONS for k in ("min", "pct_far", "prev", "patients_far")]
    V.write_csv(ROOT / "data" / "counties.csv", [county_rows[c] for c in sorted(county_rows)], cols)
    V.write_csv(ROOT / "data" / "sites.csv", all_sites, ["condition", "lat", "lon", "city", "state", "trials"])
    summary["places_note"] = "PLACES 2025 release (BRFSS 2023); Kentucky and Pennsylvania from the 2024 release (BRFSS 2022)"
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
