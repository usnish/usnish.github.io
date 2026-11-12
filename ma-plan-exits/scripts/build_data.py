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
PlanArea) includes the member's county. Regional PPOs serve whole MA regions (PBP
PlanRegionArea; region-to-state map from the Landscape file) and so keep their counties.

Also counts, by county, the plans anyone can join (not special needs plans) and the
insurers offering them in each year. Runs for the 2026 cycle (September 2025 members)
and the 2027 cycle (September 2026 members).

Insurers are grouped by parent company. CMS lists the parent per contract (H number), so a
plan's parent is looked up by its contract: first in the September enrollment file's contract
list, then, for contracts that are new next year, in the CMS Landscape file for that year.
(Looking it up by contract and plan, as an earlier version did, missed every plan ID that is
new next year and fell back to marketing names, so the same insurer showed up as both leaving
and new.)

Counties: one row per county on the site's county map (50 states and DC), with zeros where a
county has no members or no plans. Territories are left out of every total and table.

Writes data/counties.csv and data/summary.json.
Usage: python3 ma-plan-exits/scripts/build_data.py
"""
import csv
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import malib as M  # noqa: E402

CYCLES = [(2026, (2025, "September")), (2027, (2026, "September"))]
OUTCOMES = ["stays", "moved", "leaving", "ended"]
# CMS Landscape files (all approved non-employer MA, SNP and drug plans for a contract year, with
# the parent organization per contract): https://www.cms.gov/medicare/coverage/prescription-drug-coverage
LANDSCAPE = {2026: "cy2026-landscape-202609.zip", 2027: "cy2027-landscape-202611.zip"}
# Every county row covers the same fixed list: the counties on the site's county map (50 states and DC).
MAP = ROOT.parent / "assets" / "viz" / "counties-albers-10m.json"
# Retired Virginia independent cities that CMS files still carry under their own codes; each was
# folded into a county (Bedford city 2013, Clifton Forge 2001, South Boston 1995). Counted with
# that county, the same way malib.AK_FIX maps Alaska's old codes.
VA_FOLD = {"51515": "51019", "51560": "51005", "51780": "51083"}
# The insurer table shows the twelve largest insurers by membership, plus any other insurer
# with at least this many members who must choose a new plan.
BIG_EXIT = 100_000
# Short names for parent companies whose CMS legal name readers won't recognize (checked against
# the organization marketing names in the September 2026 CPSC contract file). Page-local, on top
# of malib.parent_name.
DISPLAY = [("Healthfirst", "Healthfirst"), ("MHH Healthcare", "GlobalHealth (MHH Healthcare)"),
           ("BMC Health System", "WellSense (Boston Medical Center)"),
           ("Aware Integrated", "Blue Cross MN (Aware Integrated)"),
           ("Blue Cross Blue Shield of Michigan", "Blue Cross Blue Shield of Michigan")]


USPS_FIPS = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
             "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
             "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
             "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
             "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
             "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72"}


@lru_cache(maxsize=None)
def landscape_rows(year):
    z = M.V.fetch(M.CMS + LANDSCAPE[year])
    with zipfile.ZipFile(z) as zf:
        raw = zf.read(next(n for n in zf.namelist() if n.lower().endswith(".csv")))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return tuple(csv.DictReader(io.StringIO(text)))


def display(p):
    p = M.parent_name(p)
    return next((v for k, v in DISPLAY if k.lower() in p.lower()), p)


def map_counties():
    us = json.loads(MAP.read_text())
    return {g["id"] for g in us["objects"]["counties"]["geometries"] if g["id"][:2] in M.V.STATE_FIPS}


def fold(f):
    return VA_FOLD.get(f, f)


def norm(name):
    """County name for matching across CMS files ("De Kalb" and "DeKalb", "La Salle" and "LaSalle")."""
    return "".join(ch for ch in name.lower() if ch.isalpha())


@lru_cache(maxsize=None)
def county_names(year, month):
    """{(USPS state, CMS county name): fips} from the CPSC enrollment file (same county names as Landscape)."""
    m = M.MONTHS.index(month.lower()) + 1
    z = M.V.fetch(M.CPSC.format(month=month.lower(), year=year))
    out = {}
    for r in M.zip_rows(z, f"CPSC_Enrollment_{year}_{m:02d}/CPSC_Enrollment_Info_{year}_{m:02d}.csv", ","):
        if r["FIPS State County Code"]:
            f = r["FIPS State County Code"]
            out[r["State"], norm(r["County"])] = fold(M.AK_FIX.get(f, f))
    return out


def landscape_check(year, enroll_month, area, fips_of, insurers):
    """Cross-check against the CMS Landscape file for `year` (released after the October 1 PBP files).

    Returns ({fips: insurer count in Landscape}, {fips: [insurers Landscape lists in plans whose
    October PBP service area leaves that county out]}), for plans anyone can join (no SNPs, cost
    plans or MSAs)."""
    names = county_names(*enroll_month)
    ssa_by_fips = defaultdict(set)
    for ssa, f in fips_of.items():
        ssa_by_fips[f].add(ssa)
    land, late = defaultdict(set), defaultdict(set)
    for r in landscape_rows(year):
        if r["Contract Category Type"] not in ("MA", "MA-PD") or "MSA" in r["Plan Type"]:
            continue
        f = names.get((r["State Territory Abbreviation"], norm(r["County Name"])))
        if not f:
            continue
        p = display(r["Parent Organization Name"].strip())
        land[f].add(p)
        k = (r["Contract ID"], r["Plan ID"])
        if not r["Contract ID"].startswith("R") and not (area.get(k, {}).keys() & ssa_by_fips[f]) and p not in insurers.get(f, ()):
            late[f].add(p)
    return {f: len(v) for f, v in land.items()}, {f: sorted(v) for f, v in late.items()}


def landscape_parents(year):
    """{contract: parent organization} from the CMS Landscape file for `year`."""
    out = {}
    for r in landscape_rows(year):
        if r["Parent Organization Name"].strip():
            out.setdefault(r["Contract ID"], r["Parent Organization Name"].strip())
    return out


@lru_cache(maxsize=None)
def ma_region_states():
    """{MA region code: {state FIPS}} from the Landscape files (the 26 fixed MA regions)."""
    out = defaultdict(set)
    for y in LANDSCAPE:
        for r in landscape_rows(y):
            if r["MA Region Code"] not in ("", "Not Applicable") and r["State Territory Abbreviation"] in USPS_FIPS:
                out[r["MA Region Code"]].add(USPS_FIPS[r["State Territory Abbreviation"]])
    return dict(out)


def kind(p):
    return {"": "Plans open to anyone", "Dual-eligible": "Dual-eligible special needs plans"}.get(
        p["snp"], "Other special needs plans")


def cycle(year, enroll_month):
    prev = year - 1
    plans = {y: M.plans(y) for y in (prev, year)}
    area = {y: M.plan_area(y, set(plans[y])) for y in (prev, year)}
    enroll, fips_of, contracts = M.enrollment(*enroll_month)
    fips_of = {ssa: fold(f) for ssa, f in fips_of.items()}
    folded = {}
    for k, cs in enroll.items():
        folded[k] = Counter()
        for f, n in cs.items():
            folded[k][fold(f)] += n
    enroll = folded
    # Regional PPOs are listed by MA region (PlanRegionArea), not by county, and serve every
    # county in their region's states. Add those counties to their service areas.
    ssa_by_state = defaultdict(set)
    for ssa, f in fips_of.items():
        ssa_by_state[f[:2]].add(ssa)
    regions = ma_region_states()
    for y in (prev, year):
        for r in M.zip_rows(M.pbp_zip(y), "PlanRegionArea.txt"):
            k = (r["contract_id"], r["plan_id"])
            if k in plans[y] and r["region_type"] == "MA":
                for st in regions[r["ma_or_pdp_region_code"]]:
                    for ssa in ssa_by_state[st]:
                        area[y].setdefault(k, {}).setdefault(ssa, r["segment_id"])
    xwalk = M.crosswalk(year)
    # A county can have more than one SSA code (Los Angeles: 05200 and 05210; Alaska's old codes);
    # a destination plan serves the county if its service area lists any of them.
    ssa_of = defaultdict(set)
    for ssa, f in fips_of.items():
        ssa_of[f].add(ssa)

    # Parent company by contract: September enrollment contract list first (one name per contract
    # across both years), then that year's Landscape file for contracts new next year, then any
    # Landscape year, then a match on the organization's marketing name.
    by_contract, by_org = {}, {}
    for (c, _), v in contracts.items():
        if v["parent"]:
            by_contract.setdefault(c, v["parent"])
            by_org.setdefault(v["org"].lower(), v["parent"])
    land = {y: landscape_parents(y) for y in LANDSCAPE}
    source = Counter()

    def parent(k, y):
        c, org = k[0], plans[y][k]["org"]
        for name, p in (("enrollment file", by_contract.get(c)), ("landscape, same year", land.get(y, {}).get(c)),
                        ("landscape, other year", next((l[c] for l in land.values() if c in l), None)),
                        ("marketing-name match", by_org.get(org.lower()))):
            if p:
                source[name, y] += 1
                return display(p)
        source["unmatched (marketing name)", y] += 1
        return org

    county = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    by_kind = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    by_parent = defaultdict(lambda: {o: 0 for o in OUTCOMES})
    no_xwalk, territories = 0, Counter()
    split, split_kind = 0, Counter()
    moved_status = Counter()
    for k, counties in enroll.items():
        if k not in plans[prev]:
            continue
        rows = xwalk.get(k)
        if rows is None:
            no_xwalk += sum(counties.values())
            continue
        dests = [d for _, d in rows if d and d in plans[year]]
        status = {d: st for st, d in rows if d}
        kd, pa = kind(plans[prev][k]), parent(k, prev)
        for fips, n in counties.items():
            ssa = ssa_of.get(fips, set())

            def serves(d):
                return d[0].startswith("R") or bool(area[year].get(d, {}).keys() & ssa)
            # If the plan itself renews in this county, its members stay, even when the crosswalk also
            # lists another plan for the county. CMS splits some plans in two (mostly dual-eligible plans
            # being lined up with state Medicaid contracts) by Medicaid enrollment, not by county, and
            # the crosswalk does not say which members go where; those members are counted as staying.
            own = k in dests and serves(k)
            d = k if own else next((d for d in dests if serves(d)), None)
            o = "ended" if not dests else "leaving" if d is None else "stays" if d == k else "moved"
            if fips[:2] not in M.V.STATE_FIPS:
                territories[o] += n
                continue
            if own and any(x != k and serves(x) for x in dests):
                split += n
                split_kind[kd] += n
            if o == "moved":
                moved_status[status[d]] += n
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

    land_n, late = landscape_check(year, enroll_month, area[year], fips_of, insurers[year])
    allc = map_counties()
    stray = {f for f in set(county) | set(offer[prev]) | set(offer[year]) if f[:2] in M.V.STATE_FIPS} - allc
    assert not stray, f"counties with data but not on the map: {sorted(stray)}"
    rows = {}
    for fips in sorted(allc):
        c = county[fips]
        n = sum(c.values())
        gone = sorted(insurers[prev][fips] - insurers[year][fips])
        new = sorted(insurers[year][fips] - insurers[prev][fips])
        rows[fips] = {"members": n, **c,
                      "pct_must_choose": round(100 * (c["leaving"] + c["ended"]) / n, 1) if n else "",
                      "pct_moved": round(100 * c["moved"] / n, 1) if n else "",
                      "plans_prev": len(offer[prev][fips]), "plans_next": len(offer[year][fips]),
                      "insurers_prev": len(insurers[prev][fips]), "insurers_next": len(insurers[year][fips]),
                      "insurers_gone": "; ".join(gone), "insurers_new": "; ".join(new),
                      "late_add": "; ".join(late.get(fips, []))}
    check = Counter("same" if land_n.get(f, 0) == r["insurers_next"] else "differs" for f, r in rows.items())
    differ = {f: (r["insurers_next"], land_n.get(f, 0)) for f, r in rows.items() if land_n.get(f, 0) != r["insurers_next"]}
    print(year, "insurers next year vs CMS Landscape:", dict(check), differ)
    print(year, "insurers CMS added after the October PBP files:", late)

    tot = {o: sum(r[o] for r in rows.values()) for o in OUTCOMES}
    members = sum(tot.values())
    size = lambda p: sum(by_parent[p].values())  # noqa: E731
    big = sorted(by_parent, key=lambda p: -size(p))[:12]
    big = sorted(set(big) | {p for p in by_parent if by_parent[p]["leaving"] + by_parent[p]["ended"] >= BIG_EXIT},
                 key=lambda p: -size(p))
    for o in OUTCOMES:
        assert sum(by_kind[k][o] for k in by_kind) == tot[o], o
        assert sum(by_parent[p][o] for p in by_parent) == tot[o], o
    summary = {
        "year": year, "enrollment_month": f"{enroll_month[1]} {enroll_month[0]}", "members": members, **tot,
        "pct_must_choose": round(100 * (tot["leaving"] + tot["ended"]) / members, 1),
        "pct_moved": round(100 * tot["moved"] / members, 1),
        "members_no_crosswalk": no_xwalk,
        "members_split": split, "members_split_by_kind": dict(split_kind),
        "moved_by_status": dict(moved_status),
        "territories_left_out": dict(territories),
        "counties_total": len(rows),
        "counties_no_insurer": sum(1 for r in rows.values() if r["insurers_next"] == 0),
        "counties_late_add": {f: late[f] for f in sorted(late)},
        "insurer_table_big_exit": BIG_EXIT,
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
    print(year, "parent lookups by source (calls, not plans):", dict(source))
    return rows, summary


def main():
    out, summaries = defaultdict(dict), {}
    for year, em in CYCLES:
        rows, s = cycle(year, em)
        summaries[str(year)] = s
        for fips, r in rows.items():
            for k, v in r.items():
                out[fips][f"{k}_{year}"] = v
    # The 2026 cycle's next-year plans and the 2027 cycle's previous-year plans are the same 2026
    # plans; their insurer counts should agree except where a contract changed parent company
    # between the two September files.
    diff = sum(1 for r in out.values() if r["insurers_next_2026"] != r["insurers_prev_2027"]
               or r["plans_next_2026"] != r["plans_prev_2027"])
    print("counties where 2026 plan or insurer counts differ between cycles:", diff)
    assert diff == 0
    assert summaries["2027"]["counties_one_or_no_insurer_prev"] == summaries["2026"]["counties_one_or_no_insurer"]
    cols = ["fips"] + [f"{k}_{y}" for y, _ in CYCLES for k in
                       ["members", *OUTCOMES, "pct_must_choose", "pct_moved", "plans_prev", "plans_next",
                        "insurers_prev", "insurers_next", "insurers_gone", "insurers_new", "late_add"]]
    (ROOT / "data").mkdir(exist_ok=True)
    M.V.write_csv(ROOT / "data" / "counties.csv", [{"fips": f, **out[f]} for f in sorted(out)], cols)
    (ROOT / "data" / "summary.json").write_text(json.dumps(summaries, indent=1) + "\n")


if __name__ == "__main__":
    main()
