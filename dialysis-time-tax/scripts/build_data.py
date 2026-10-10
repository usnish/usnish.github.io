"""Build the dialysis "time tax" data.

For every 2020 census tract, find the nearest Medicare-certified dialysis center
that offers in-center hemodialysis, convert the straight-line distance to an
estimated driving time (calibrated against real routes, see _viz/calibrate_drive.py),
and compute the travel time a resident on in-center dialysis would spend per year:
3 sessions a week x 52 weeks x a round trip.

Rolls tracts up to counties (population-weighted) and joins CDC/ATSDR SVI 2022 for
households without a vehicle and overall social vulnerability.

Writes data/counties.csv, data/facilities.csv, data/summary.json.
Usage: python3 dialysis-time-tax/scripts/build_data.py   (needs numpy, scipy)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

LISTING = "https://data.cms.gov/provider-data/api/1/datastore/query/23ew-n7w9/0"
SESSIONS_PER_YEAR = 3 * 52
FAR_MIN = 30  # one-way minutes considered far for a thrice-weekly trip
MAX_KM = 150  # beyond the calibration range; mostly Alaska communities reached by air or water


def facilities():
    rows, offset = [], 0
    while True:
        j = V.get_json(LISTING, {"limit": 1500, "offset": offset})
        rows += j["results"]
        offset += 1500
        if offset >= j["count"]:
            break
    rows = [r for r in rows if r["offers_incenter_hemodialysis"] == "Yes"]
    st = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
          "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
          "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
          "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
          "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
          "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56"}
    rows = [r for r in rows if r["state"] in st]
    geo = V.geocode([{"id": r["cms_certification_number_ccn"], "street": r["address_line_1"], "city": r["citytown"],
                      "state": r["state"], "zip": r["zip_code"]} for r in rows], "dialysis_geocode.json")
    out = []
    for r in rows:
        g = geo.get(r["cms_certification_number_ccn"])
        if not g:
            continue
        out.append({"ccn": r["cms_certification_number_ccn"], "name": r["facility_name"].title(), "city": r["citytown"].title(),
                    "state": r["state"], "lat": round(g[0], 5), "lon": round(g[1], 5), "geocode": g[2],
                    "stations": r["of_dialysis_stations"], "stars": r["five_star"], "profit": r["profit_or_nonprofit"],
                    "chain": r["chain_organization"], "late_shift": r["late_shift"]})
    print(f"facilities: {len(out)} in-center hemodialysis ({sum(f['geocode'] == 'zip' for f in out)} placed at ZIP centroid, "
          f"{len(rows) - len(out)} not located)")
    return out


def main():
    fac = facilities()
    minutes, model = V.drive_model()
    rucc = V.rucc()
    svi = V.svi_tracts()
    tracts = [t for t in V.tract_centers() if t["pop"] > 0]

    km, idx = V.nearest([t["lat"] for t in tracts], [t["lon"] for t in tracts],
                        [f["lat"] for f in fac], [f["lon"] for f in fac])
    metro = lambda c: V.is_metro(c, rucc)  # noqa: E731
    for t, d, i in zip(tracts, km, idx):
        t["km"] = float(d)
        t["beyond"] = t["km"] > MAX_KM
        t["min"] = max(minutes(float(d), metro(t["county"])), 2.0)
        t["hours"] = t["min"] * 2 * SESSIONS_PER_YEAR / 60
        s = svi(t["geoid"]) or {}
        t["noveh"] = V.num(s.get("E_NOVEH")) or 0
        t["hh"] = V.num(s.get("E_HH")) or 0
        t["svi"] = V.num(s.get("RPL_THEMES"))

    # County roll-up (population-weighted means; household counts summed)
    agg = defaultdict(lambda: defaultdict(float))
    for t in tracts:
        a = agg[t["county"]]
        a["pop"] += t["pop"]
        a["min_w"] += t["min"] * t["pop"]
        a["hours_w"] += t["hours"] * t["pop"]
        a["far_pop"] += t["pop"] if t["min"] > FAR_MIN else 0
        a["hh"] += t["hh"]
        a["noveh"] += t["noveh"]
        a["noveh_far"] += t["noveh"] if t["min"] > FAR_MIN else 0
        a["max_min"] = max(a["max_min"], t["min"])
        a["beyond_pop"] += t["pop"] if t["beyond"] else 0
    cty_svi = {r["FIPS"].zfill(5): V.num(r["RPL_THEMES"]) for r in V.read_csv(V.fetch(V.SVI_COUNTY))}
    counties = []
    for c, a in sorted(agg.items()):
        counties.append({"fips": c, "pop": int(a["pop"]),
                         "one_way_min": round(a["min_w"] / a["pop"], 1),
                         "annual_hours": round(a["hours_w"] / a["pop"]),
                         "pct_far": round(100 * a["far_pop"] / a["pop"], 1),
                         "households": int(a["hh"]), "no_vehicle_hh": int(a["noveh"]),
                         "no_vehicle_far_hh": int(a["noveh_far"]),
                         "max_one_way_min": round(a["max_min"]),
                         "pct_beyond_range": round(100 * a["beyond_pop"] / a["pop"]),
                         "metro": int(metro(c)), "svi": cty_svi.get(c, "")})

    # National summary, leaving out tracts beyond the drive model's range
    beyond = [t for t in tracts if t["beyond"]]
    tracts = [t for t in tracts if not t["beyond"]]
    pop = np.array([t["pop"] for t in tracts], float)
    hrs = np.array([t["hours"] for t in tracts])
    mins = np.array([t["min"] for t in tracts])
    w_median = lambda v, w: float(v[np.argsort(v)][np.searchsorted(np.cumsum(w[np.argsort(v)]), w.sum() / 2)])  # noqa: E731
    quart, noveh_q = {}, {}
    for q, lo, hi in [("Least vulnerable quarter", 0, .25), ("2nd", .25, .5), ("3rd", .5, .75), ("Most vulnerable quarter", .75, 1.01)]:
        g = [t for t in tracts if t["svi"] is not None and lo <= t["svi"] < hi]
        quart[q] = round(sum(t["pop"] * t["hours"] for t in g) / sum(t["pop"] for t in g))
        noveh_q[q] = round(100 * sum(t["noveh"] for t in g) / sum(t["hh"] for t in g), 1)
    m_mask = np.array([metro(t["county"]) for t in tracts])
    summary = {
        "facilities": len(fac),
        "beyond_range_km": MAX_KM,
        "beyond_range_pop": sum(t["pop"] for t in beyond),
        "beyond_range_states": sorted({t["state"] for t in beyond}),
        "median_one_way_min": round(w_median(mins, pop), 1),
        "median_annual_hours": round(w_median(hrs, pop)),
        "metro_mean_annual_hours": round(float((hrs * pop)[m_mask].sum() / pop[m_mask].sum())),
        "nonmetro_mean_annual_hours": round(float((hrs * pop)[~m_mask].sum() / pop[~m_mask].sum())),
        "people_far": int(pop[mins > FAR_MIN].sum()),
        "pct_people_far": round(100 * float(pop[mins > FAR_MIN].sum() / pop.sum()), 1),
        "no_vehicle_hh": int(sum(t["noveh"] for t in tracts)),
        "no_vehicle_far_hh": int(sum(t["noveh"] for t in tracts if t["min"] > FAR_MIN)),
        "hours_by_svi_quarter": quart,
        "pct_no_vehicle_by_svi_quarter": noveh_q,
        "far_minutes": FAR_MIN,
        "sessions_per_year": SESSIONS_PER_YEAR,
        "drive_model": {k: model[k] for k in ("metro", "nonmetro")},
    }
    print(json.dumps(summary, indent=2))

    V.write_csv(ROOT / "data" / "counties.csv", counties, list(counties[0].keys()))
    V.write_csv(ROOT / "data" / "facilities.csv", fac,
                ["ccn", "name", "city", "state", "lat", "lon", "stations", "stars", "profit", "chain", "late_shift"])
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
