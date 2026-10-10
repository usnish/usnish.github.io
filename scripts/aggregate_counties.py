"""Roll county-level cardiac rehab data up to states.

Usage:
  python scripts/aggregate_counties.py COUNTY_CSV \
      --fips-col FIPS --eligible-col eligible --rate-col participation_pct

Each state's rate is the eligible-weighted mean of its counties' rates
(equivalently, total participants / total eligible). Counties with missing
or suppressed values are skipped and counted in the printed summary.
Writes data/state_cr.csv, keeping the state name/abbreviation columns.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "state_cr.csv"


def num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("county_csv")
    ap.add_argument("--fips-col", required=True, help="5-digit county FIPS column")
    ap.add_argument("--eligible-col", required=True, help="number of CR-eligible patients")
    ap.add_argument("--rate-col", help="participation rate in percent (0-100)")
    ap.add_argument("--participants-col", help="number who participated (alternative to --rate-col)")
    a = ap.parse_args()
    if not (a.rate_col or a.participants_col):
        ap.error("pass --rate-col or --participants-col")

    elig = defaultdict(float)
    part = defaultdict(float)
    used = skipped = 0
    with open(a.county_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fips = str(row[a.fips_col]).strip().zfill(5)
            e = num(row[a.eligible_col])
            if a.participants_col:
                p = num(row[a.participants_col])
            else:
                r = num(row[a.rate_col])
                p = e * r / 100 if e is not None and r is not None else None
            if not e or p is None:
                skipped += 1
                continue
            elig[fips[:2]] += e
            part[fips[:2]] += p
            used += 1

    with open(OUT, newline="") as f:
        states = list(csv.DictReader(f))
    for s in states:
        st = s["fips"].zfill(2)
        if elig.get(st):
            s["eligible"] = round(elig[st])
            s["participants"] = round(part[st])
            s["participation_pct"] = round(100 * part[st] / elig[st], 1)
        else:
            s["eligible"] = s["participants"] = s["participation_pct"] = ""
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=states[0].keys())
        w.writeheader()
        w.writerows(states)

    total_e, total_p = sum(elig.values()), sum(part.values())
    print(f"counties used: {used}, skipped: {skipped}, states filled: {len(elig)}")
    if total_e:
        print(f"overall participation: {100 * total_p / total_e:.1f}% of {total_e:,.0f} eligible")


if __name__ == "__main__":
    main()
