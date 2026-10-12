"""Build the Medicare Advantage plan exits data.

Every fall, CMS publishes a plan crosswalk showing what happens to each plan's members
in the coming year: the plan renews, is merged into another plan, drops some counties
(a service area reduction), or ends. This follows every member of an individual
Medicare Advantage plan (CMS enrollment by plan and county, September) through the
crosswalk into the next year:

  - stays:   their plan renews and still serves their county
  - moved:   they are moved automatically into a different plan that serves their county
  - leaving: their plan renews but drops their county; they must choose a new plan
  - ended:   their plan ends outright; they must choose a new plan

A crosswalk destination counts only if the next year's plan service area (PBP
PlanArea) includes the member's county. Regional PPOs serve whole regions and are
taken to keep their counties.

Also counts, by county, the plans anyone can join (not special needs plans) and the
insurers offering them in each year. Runs for the 2026 cycle (September 2025 members)
and the 2027 cycle (September 2026 members).

Writes data/counties.csv and data/summary.json.
Usage: python3 ma-plan-exits/scripts/build_data.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import malib as M  # noqa: E402

CYCLES = [(2026, (2025, "September")), (2027, (2026, "September"))]
OUTCOMES = ["stays", "moved", "leaving", "ended"]


def kind(p):
    return {"": "Plans open to anyone", "Dual-eligible": "Dual-eligible special needs plans"}.get(
        p["snp"], "Other special needs plans")


def cycle(year, enroll_month):
    prev = year - 1
    plans = {y: M.plans(y) for y in (prev, year)}
    area = {y: M.plan_area(y, set(plans[y])) for y in (prev, year)}
    enroll, fips_of, contracts = M.enrollment(*enroll_month)
    xwalk = M.crosswalk(year)
    ssa_of = {}
    for ssa, f in fips_of.items():
        ssa_of.setdefault(f, ssa)

    def parent(k, y):
        p = contracts.get(k, {}).get("parent") or plans[y][k]["org"]
        return M.parent_name(p)

    county = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    by_kind = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    by_parent = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    no_xwalk = 0
    for k, counties in enroll.items():
        if k not in plans[prev]:
            continue
        rows = xwalk.get(k)
        if rows is None:
            no_xwalk += sum(counties.values())
            continue
        dests = [d for _, d in rows if d and d in plans[year]]
        kd, pa = kind(plans[prev][k]), parent(k, prev)
        for fips, n in counties.items():
            ssa = ssa_of.get(fips)
            d = next((d for d in dests if ssa in area[year].get(d, {}) or d[0].startswith("R")), None)
            o = "ended" if not dests else "leaving" if d is None else "stays" if d == k else "moved"
            county[fips][o] += n
            by_kind[kd][o] += n
            by_parent[pa][o] += n

    # Plans anyone can join (no SNPs), and their insurers, by county and year
    offer = {y: defaultdict(set) for y in (prev, year)}
    insurers = {y: defaultdict(set) for y in (prev, year)}
    for y in (prev, year):
        for k, cs in area[y].items():
            if plans[y][k]["snp"]:
                continue
            for ssa in cs:
                f = fips_of.get(ssa)
                if f:
                    offer[y][f].add(k)
                    insurers[y][f].add(parent(k, y))

    rows = {}
    for fips in set(county) | set(offer[prev]) | set(offer[year]):
        if fips[:2] not in M.V.STATE_FIPS:
            continue
        c = county[fips]
        n = sum(c.values())
        gone = sorted(insurers[prev][fips] - insurers[year][fips])
        new = sorted(insurers[year][fips] - insurers[prev][fips])
        rows[fips] = {"members": n, **c,
                      "pct_must_choose": round(100 * (c["leaving"] + c["ended"]) / n, 1) if n else "",
                      "pct_moved": round(100 * c["moved"] / n, 1) if n else "",
                      "plans_prev": len(offer[prev][fips]), "plans_next": len(offer[year][fips]),
                      "insurers_prev": len(insurers[prev][fips]), "insurers_next": len(insurers[year][fips]),
                      "insurers_gone": "; ".join(gone), "insurers_new": "; ".join(new)}

    tot = {o: sum(r[o] for r in rows.values()) for o in OUTCOMES}
    members = sum(tot.values())
    big = sorted(by_parent, key=lambda p: -sum(by_parent[p].values()))[:12]
    summary = {
        "year": year, "enrollment_month": f"{enroll_month[1]} {enroll_month[0]}", "members": members, **tot,
        "pct_must_choose": round(100 * (tot["leaving"] + tot["ended"]) / members, 1),
        "pct_moved": round(100 * tot["moved"] / members, 1),
        "members_no_crosswalk": no_xwalk,
        "counties_lost_plans": sum(1 for r in rows.values() if r["plans_next"] < r["plans_prev"]),
        "counties_gained_plans": sum(1 for r in rows.values() if r["plans_next"] > r["plans_prev"]),
        "counties_insurer_left": sum(1 for r in rows.values() if r["insurers_gone"]),
        "counties_one_or_no_insurer": sum(1 for r in rows.values() if r["insurers_next"] <= 1),
        "counties_one_or_no_insurer_prev": sum(1 for r in rows.values() if r["insurers_prev"] <= 1),
        "plans_prev": len({k for k in plans[prev] if not plans[prev][k]["snp"]}),
        "plans_next": len({k for k in plans[year] if not plans[year][k]["snp"]}),
        "by_kind": [{"name": k, **by_kind[k]} for k in ("Plans open to anyone", "Dual-eligible special needs plans", "Other special needs plans")],
        "by_insurer": [{"name": p, **by_parent[p]} for p in big],
        "statuses": {s: sum(1 for rs in xwalk.values() for st, _ in rs if st == s) for s in
                     {st for rs in xwalk.values() for st, _ in rs}},
    }
    print(year, json.dumps({k: v for k, v in summary.items() if k not in ("by_insurer",)}, indent=1))
    return rows, summary


def main():
    out, summaries = defaultdict(dict), {}
    for year, em in CYCLES:
        rows, s = cycle(year, em)
        summaries[str(year)] = s
        for fips, r in rows.items():
            for k, v in r.items():
                out[fips][f"{k}_{year}"] = v
    cols = ["fips"] + [f"{k}_{y}" for y, _ in CYCLES for k in
                       ["members", *OUTCOMES, "pct_must_choose", "pct_moved", "plans_prev", "plans_next",
                        "insurers_prev", "insurers_next", "insurers_gone", "insurers_new"]]
    (ROOT / "data").mkdir(exist_ok=True)
    M.V.write_csv(ROOT / "data" / "counties.csv", [{"fips": f, **out[f]} for f in sorted(out)], cols)
    (ROOT / "data" / "summary.json").write_text(json.dumps(summaries, indent=1) + "\n")


if __name__ == "__main__":
    main()
