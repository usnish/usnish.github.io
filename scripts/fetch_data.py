"""Download county-level data on cardiac rehab-eligible conditions.

Usage:
  python3 scripts/fetch_data.py

Writes data/counties.csv (one row per county, one column per measure) and
data/measures.json (titles, units and sources, read by index.html).

Sources:
  - CDC Interactive Atlas of Heart Disease and Stroke (heart-stroke-atlas.cdc.gov),
    Medicare fee-for-service claims, beneficiaries 65+.
  - CDC PLACES county estimates (data.cdc.gov), BRFSS-based model, adults 18+.
"""
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATLAS = "https://heart-stroke-atlas.cdc.gov/api/api/data"
PLACES = "https://data.cdc.gov/resource/swc5-untb.json"  # PLACES county data, 2025 release

# Atlas hospitalization themes need explicit filters: 2019-2021, all races,
# both sexes, ages 65+, spatially smoothed.
HOSP_FILTERS = [{"FilterId": i, "FilterOptionId": o} for i, o in [(1, 1), (5, 1), (3, 1), (6, 1), (7, 1)]]

ATLAS_MEASURES = [
    # id, ThemeClassId, ThemeSubClassId, ThemeId, filters, short label
    ("cr_eligible", 3, 26, 90, [], "CR-eligible events"),
    ("ami_hosp", 1, 3, 9, HOSP_FILTERS, "Heart attack hospitalizations"),
    ("chd_hosp", 1, 2, 6, HOSP_FILTERS, "Coronary heart disease hospitalizations"),
    ("hf_hosp", 1, 5, 15, HOSP_FILTERS, "Heart failure hospitalizations"),
    ("cr_participation", 3, 26, 91, [], "CR participation among eligible"),
]


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def get(url, params):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=120) as r:
        return json.load(r)


def main():
    rows, measures = {}, []

    for mid, cls, sub, theme, filters, label in ATLAS_MEASURES:
        j = post(ATLAS, {"CountyVersion": "2018", "GeographyType": "county", "ParentGeographyFilter": "",
                         "ThemeClassId": cls, "ThemeSubClassId": sub, "ThemeId": theme,
                         "ThemeFilterOptions": filters})
        for d in j["Data"]:
            r = rows.setdefault(d["Key"], {"fips": d["Key"], "county": d["DisplayText"], "state": d["ParentText"]})
            r[mid] = d["Value"] if d["Value"] is not None and d["Value"] >= 0 else ""
        measures.append({"id": mid, "label": label, "title": j["TitleLong"], "unit": j["TitleLegend"],
                         "source": "; ".join(f'{s["Title"]}, {s["Description"]}' for s in j["DataSources"]),
                         "source_url": "https://heart-stroke-atlas.cdc.gov/"})
        print(f"{mid}: {sum(1 for r in rows.values() if r.get(mid) != '')} counties")

    places = get(PLACES, {"measureid": "CHD", "datavaluetypeid": "AgeAdjPrv", "$limit": 5000})
    year = places[0]["year"]
    places = [d for d in places if len(d.get("locationid", "")) == 5]  # skip the national row
    for d in places:
        r = rows.setdefault(d["locationid"], {"fips": d["locationid"], "county": d["locationname"], "state": d["stateabbr"]})
        r["chd_prev"] = d.get("data_value", "")  # suppressed for tiny populations
    measures.append({"id": "chd_prev", "label": "Coronary heart disease prevalence",
                     "title": f"Coronary heart disease among adults 18+, age-adjusted prevalence, {year}",
                     "unit": "% of adults (age-adjusted)",
                     "source": f"CDC PLACES 2025 release (BRFSS {year} model-based estimates)",
                     "source_url": "https://www.cdc.gov/places/"})
    print(f"chd_prev: {len(places)} counties")

    cols = ["fips", "county", "state"] + [m["id"] for m in measures]
    with open(ROOT / "data" / "counties.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["fips"]))
    with open(ROOT / "data" / "measures.json", "w") as f:
        json.dump(measures, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
