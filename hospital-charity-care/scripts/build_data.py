"""Build the nonprofit hospital charity care data.

From CMS's Hospital Provider Cost Report (HCRIS) for 2023, take every nonprofit
short-term acute care and critical access hospital and its reported charity care
(at cost). For context, also compute a rough, partial estimate of its federal
income tax exemption: 21% of positive net income. State and local exemptions,
tax-exempt bonds and deductible donations are not included.

Hospitals are geocoded with the Census geocoder and placed in counties; county
uninsured and poverty rates come from CDC/ATSDR SVI 2022 (ACS 2018-2022).

Writes data/hospitals.csv, data/counties.csv, data/summary.json.
Usage: python3 hospital-charity-care/scripts/build_data.py   (needs numpy, scipy)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

HCRIS = ("https://data.cms.gov/sites/default/files/2026-10/e48e1326-aeeb-4ad4-acf6-a506871b6d20/"
         "CostReport_2023_Final.csv")
YEAR = 2023
FED_RATE = 0.21
MAX_MARGIN = 0.5  # net income above half of total costs is almost always a one-time gain or a reporting error
NONPROFIT = {"1": "Nonprofit (church)", "2": "Nonprofit (other)"}
TYPES = {"STH": "Short-term acute care", "CAH": "Critical access"}
STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
          "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
          "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}


def hospitals():
    rows = V.read_csv(V.fetch(HCRIS, f"hcris_{YEAR}.csv"))
    latest = {}
    for r in rows:
        if r["Type of Control"] not in NONPROFIT or r["CCN Facility Type"] not in TYPES or r["State Code"] not in STATES:
            continue
        ccn = r["Provider CCN"]
        if ccn not in latest or r["Fiscal Year End Date"] > latest[ccn]["Fiscal Year End Date"]:
            latest[ccn] = r
    out, dropped, outliers = [], 0, []
    for r in latest.values():
        costs, net = V.num(r["Total Costs"]), V.num(r["Net Income"])
        if not costs or costs <= 0 or net is None:
            dropped += 1
            continue
        if net > MAX_MARGIN * costs:
            outliers.append(r["Hospital Name"].title())
            continue
        charity = V.num(r["Cost of Charity Care"]) or 0.0
        tax = FED_RATE * max(net, 0.0)
        out.append({
            "ccn": r["Provider CCN"], "name": r["Hospital Name"].title(), "street": r["Street Address"],
            "city": r["City"].title(), "state": r["State Code"], "zip": r["Zip Code"][:5],
            "type": TYPES[r["CCN Facility Type"]], "control": NONPROFIT[r["Type of Control"]],
            "beds": int(V.num(r["Number of Beds"]) or 0), "fy_end": r["Fiscal Year End Date"],
            "total_costs": round(costs), "net_income": round(net), "charity_care": round(charity),
            "fed_tax_est": round(tax),
            "charity_pct_costs": round(100 * charity / costs, 2),
            # None when there was no positive income to tax
            "charity_to_tax": round(charity / tax, 2) if tax > 0 else "",
            "gap": round(tax - charity),
        })
    print(f"hospitals: {len(out)} nonprofit STH/CAH ({dropped} dropped for missing costs or income, "
          f"{len(outliers)} for net income above {MAX_MARGIN:.0%} of costs)")
    return out, dropped, outliers


def main():
    hosp, dropped, outliers = hospitals()
    geo = V.geocode([{"id": h["ccn"], "street": h["street"], "city": h["city"], "state": h["state"], "zip": h["zip"]}
                     for h in hosp], "hospital_geocode.json")
    hosp = [h for h in hosp if h["ccn"] in geo]
    for h in hosp:
        h["lat"], h["lon"], h["geocode"] = round(geo[h["ccn"]][0], 5), round(geo[h["ccn"]][1], 5), geo[h["ccn"]][2]

    # County context from SVI tracts, rolled up to 2020 counties (matches the map shapes)
    svi = V.svi_tracts()
    tracts = [t for t in V.tract_centers() if t["pop"] > 0]
    agg = defaultdict(lambda: [0.0, 0.0, 0.0])
    for t in tracts:
        s = svi(t["geoid"]) or {}
        tot = V.num(s.get("E_TOTPOP")) or 0
        if tot:
            a = agg[t["county"]]
            a[0] += tot
            a[1] += V.num(s.get("E_UNINSUR")) or 0
            a[2] += V.num(s.get("E_POV150")) or 0
    counties = [{"fips": c, "pop": round(a[0]), "pct_uninsured": round(100 * a[1] / a[0], 1),
                 "pct_poverty150": round(100 * a[2] / a[0], 1)} for c, a in sorted(agg.items()) if a[0]]
    cmap = {c["fips"]: c for c in counties}

    # Place each hospital in the county of its nearest tract population center
    _, idx = V.nearest([h["lat"] for h in hosp], [h["lon"] for h in hosp],
                       [t["lat"] for t in tracts], [t["lon"] for t in tracts])
    for h, i in zip(hosp, idx):
        h["county"] = tracts[int(i)]["county"]
        h["county_uninsured"] = cmap.get(h["county"], {}).get("pct_uninsured", "")

    tax = np.array([h["fed_tax_est"] for h in hosp], float)
    ch = np.array([h["charity_care"] for h in hosp], float)
    pct = np.array([h["charity_pct_costs"] for h in hosp])
    unins = np.array([h["county_uninsured"] if h["county_uninsured"] != "" else np.nan for h in hosp])
    taxed = tax > 0
    quart = {}
    qs = np.nanquantile(unins, [.25, .5, .75])
    for q, lo, hi in [("Lowest uninsured quarter", -1, qs[0]), ("2nd", qs[0], qs[1]), ("3rd", qs[1], qs[2]), ("Highest uninsured quarter", qs[2], 101)]:
        m = (unins > lo) & (unins <= hi)
        quart[q] = {"hospitals": int(m.sum()), "median_charity_pct_costs": round(float(np.median(pct[m])), 2),
                    "pct_charity_below_tax": round(100 * float(((ch < tax) & taxed & m).sum() / (taxed & m).sum()), 1),
                    "uninsured_range": [round(float(max(lo, np.nanmin(unins))), 1), round(float(min(hi, np.nanmax(unins))), 1)]}
    summary = {
        "year": YEAR, "fed_rate": FED_RATE, "hospitals": len(hosp),
        "dropped_missing": dropped, "excluded_outliers": len(outliers), "max_margin": MAX_MARGIN,
        "geocoded_at_zip": sum(h["geocode"] == "zip" for h in hosp),
        "with_positive_income": int(taxed.sum()),
        "fed_tax_est_total": round(float(tax.sum())),
        "charity_total": round(float(ch.sum())),
        "charity_total_profitable": round(float(ch[taxed].sum())),
        "pct_profitable_charity_below_tax": round(100 * float(((ch < tax) & taxed).sum() / taxed.sum()), 1),
        "median_charity_pct_costs": round(float(np.median(pct)), 2),
        "by_county_uninsured": quart,
    }
    print(json.dumps(summary, indent=2))
    cols = ["ccn", "name", "city", "state", "lat", "lon", "type", "control", "beds", "fy_end", "total_costs", "net_income",
            "charity_care", "fed_tax_est", "charity_pct_costs", "charity_to_tax", "gap", "county", "county_uninsured"]
    V.write_csv(ROOT / "data" / "hospitals.csv", sorted(hosp, key=lambda h: h["ccn"]), cols)
    V.write_csv(ROOT / "data" / "counties.csv", counties, ["fips", "pct_uninsured", "pct_poverty150"])
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
