"""Build the data for "Where a Medicare plan has to put your denial letter in your language".

Medicare Advantage and Part D plans must translate required materials (Evidence of
Coverage, Annual Notice of Change, denial and appeal notices, formulary...) into any
non-English language that is "the primary language of at least 5 percent of the
individuals in a plan benefit package (PBP) service area" (42 CFR 422.2267(a)(2),
423.2267(a)(2)). This script measures, language by language, how many people with
limited English live where that line is crossed.

Two ways to read "primary language of at least 5 percent":
  lep  CMS's published method (HPMS memo, July 15 2011, Appendix A): people 5+ who
       speak the language and speak English less than "very well", divided by all
       people 5+ in the service area.
  all  the most generous reading: everyone 5+ who speaks the language at home,
       however well they speak English, divided by all people 5+.

Three service-area geographies:
  county   every county treated as its own plan (an upper bound: real plans pool counties);
           counties under 10,000 people aged 5+ are left out as too small to be a plan.
  plans    the real CY2027 service areas of every individual (non-employer) plan in the CMS
           PBP benefits file: MA plans by county (PlanArea), regional PPOs by MA region and
           stand-alone drug plans by PDP region (PlanRegionArea). A person counts as reached
           when at least one plan open to anyone with Medicare in their county (no special
           needs plans, PACE or employer plans) must translate into their language.
  enrolled the CY2026 plans weighted by September 2026 enrollment (CMS CPSC file): the share
           of each county's individual MA and PDP members who sit in a plan that must
           translate into the language, averaged over that language's limited-English speakers.
  state    every state as one service area (a stand-alone drug plan region is a state or a
           group of states).

Data: ACS 2020-2024 5-year table-based summary files C16001 (county, state, tract),
B16001 (state, PUMA) and B16004 (county), all downloaded without a key.

Writes data/coverage.csv, data/counties.csv, data/age.csv, data/languages.csv,
data/plans.csv, data/summary.json (and data/policy.json, written by hand).
Usage: python3 medicare-translation-line/scripts/build_data.py
"""
import csv
import io
import json
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402
import malib as M  # noqa: E402

OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)
SF = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/"
DAT = SF + "data/5YRData/acsdt5y2024-{t}.dat"
GEOS = SF + "documentation/Geos20245YR.txt"
SHELLS = SF + "documentation/ACS20245YR_Table_Shells.txt"

FLOOR = 10000       # smallest county (people 5+) treated as a possible service area
THRESH = 0.05
PLAN_YEAR = 2027

# C16001 line of the "speaks the language" total; "speaks English less than very well" is line + 2
LANGS = {"Spanish": 3, "Chinese": 21, "Vietnamese": 24, "Korean": 18, "Tagalog": 27, "Arabic": 33}
# grouped C16001 categories, used only to compare with CMS's own 2023 statement
GROUPS = {"Other Asian and Pacific Island languages": 30, "French, Haitian or Cajun": 6,
          "Russian, Polish or other Slavic": 12, "German or other West Germanic": 9,
          "Other Indo-European": 15, "Other and unspecified": 36}
LABEL = {"C16001_003": "Spanish:", "C16001_018": "Korean:", "C16001_021": "Chinese (incl. Mandarin, Cantonese):",
         "C16001_024": "Vietnamese:", "C16001_027": "Tagalog (incl. Filipino):", "C16001_033": "Arabic:"}
CT_NAMES = {"09001": "Fairfield", "09003": "Hartford", "09005": "Litchfield", "09007": "Middlesex",
            "09009": "New Haven", "09011": "New London", "09013": "Tolland", "09015": "Windham"}
# Valdez-Cordova split in 2019; CMS still lists the old borough
AK_SPLIT = {"02261": ["02063", "02066"]}
STATES = ["District of Columbia", "West Virginia", "New Hampshire", "New Jersey", "New Mexico", "New York",
          "North Carolina", "North Dakota", "South Carolina", "South Dakota", "Rhode Island", "Alabama", "Alaska",
          "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida", "Georgia",
          "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
          "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
          "Nevada", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Tennessee", "Texas", "Utah", "Vermont",
          "Virginia", "Washington", "Wisconsin", "Wyoming"]


def n(x):
    v = V.num(x)
    return 0.0 if v is None or v < 0 else v  # negative values are Census annotation codes


def read_dat(table, prefixes):
    """Rows of a table-based summary file whose GEO_ID starts with one of `prefixes`."""
    path = V.fetch(DAT.format(t=table))
    out = {}
    with open(path, encoding="latin-1") as f:
        head = f.readline().rstrip("\n").split("|")
        for line in f:
            if not line.startswith(prefixes):
                continue
            r = line.rstrip("\n").split("|")
            out[r[0]] = dict(zip(head, r))
    return out


def check_shells():
    """Fail loudly if the C16001 line numbers no longer mean what this script assumes."""
    labels = {}
    with open(V.fetch(SHELLS), encoding="latin-1") as f:
        for line in f:
            p = line.split("|")
            if len(p) > 4 and p[0] == "C16001":
                labels[p[3]] = p[4]
    for uid, lab in LABEL.items():
        assert labels.get(uid) == lab, (uid, labels.get(uid))
        nxt = f"C16001_{int(uid[-3:]) + 2:03d}"
        assert labels[nxt] == 'Speak English less than "very well"', nxt
    assert labels["C16001_001"] == "Total:"


def geo_names():
    names = {}
    with open(V.fetch(GEOS), encoding="latin-1") as f:
        head = f.readline().rstrip("\n").split("|")
        gi, ni = head.index("GEO_ID"), head.index("NAME")
        for line in f:
            r = line.rstrip("\n").split("|")
            if len(r) > ni and r[gi][:9] in ("0500000US", "0400000US", "795P200US"):
                names[r[gi]] = r[ni]
    return names


def lang_values(r, line, pref="C16001"):
    e = lambda i: n(r[f"{pref}_E{i:03d}"])
    m = lambda i: n(r[f"{pref}_M{i:03d}"])
    return {"all": e(line), "lep": e(line + 2), "all_m": m(line), "lep_m": m(line + 2)}


def share_moe(x, mx, y, my):
    """Census formula for the 90% MOE of a proportion x / y."""
    if y <= 0:
        return 0.0
    p = x / y
    rad = mx ** 2 - p ** 2 * my ** 2
    if rad < 0:
        rad = mx ** 2 + p ** 2 * my ** 2
    return math.sqrt(rad) / y


# ---------------------------------------------------------------------------
# ACS: counties, states, Connecticut's old counties (rebuilt from tracts)

def load_acs():
    check_shells()
    rows = read_dat("c16001", ("0500000US", "0400000US", "1400000US09"))
    names = geo_names()
    counties, states = {}, {}
    for gid, r in rows.items():
        st = gid[9:11]
        if st == "72":
            continue
        rec = {"pop5": n(r["C16001_E001"]), "pop5_m": n(r["C16001_M001"]),
               "langs": {k: lang_values(r, v) for k, v in {**LANGS, **GROUPS}.items()}}
        if gid.startswith("0500000US"):
            nm = names.get(gid, gid)
            rec.update(fips=gid[9:], name=nm.split(",")[0], state=nm.split(", ")[-1])
            counties[gid[9:]] = rec
        elif gid.startswith("0400000US"):
            rec.update(fips=st, name=names.get(gid, st))
            states[st] = rec
    # Connecticut: ACS now reports planning regions, CMS plan areas still use the 8 old counties.
    tract_county = {t["state"] + t["tractce"]: t["county"] for t in V.tract_centers() if t["state"] == "09"}
    ct, missed = {}, 0
    for gid, r in rows.items():
        if not gid.startswith("1400000US09"):
            continue
        old = tract_county.get("09" + gid[-6:])
        if old is None:
            missed += n(r["C16001_E001"])
            continue
        c = ct.setdefault(old, {"fips": old, "name": CT_NAMES[old] + " County", "state": "Connecticut",
                                "pop5": 0.0, "langs": defaultdict(lambda: {"all": 0.0, "lep": 0.0})})
        c["pop5"] += n(r["C16001_E001"])
        for k, v in {**LANGS, **GROUPS}.items():
            lv = lang_values(r, v)
            c["langs"][k]["all"] += lv["all"]
            c["langs"][k]["lep"] += lv["lep"]
    print(f"  Connecticut tracts not matched to an old county: {missed:.0f} people 5+")
    plan_units = {f: c for f, c in counties.items() if not f.startswith("09")}
    plan_units.update(ct)
    return counties, states, plan_units


# ---------------------------------------------------------------------------
# CMS plan service areas

def region_states(name):
    """State FIPS codes named in a CMS region label, e.g. 'Pennsylvania, West Virginia'."""
    abbr = {}
    for f, s in STATE_NAME.items():
        abbr[s] = f
    found, rest = [], name
    for s in STATES:  # longest/compound names first so 'West Virginia' is not read as 'Virginia'
        if s in rest:
            found.append(abbr[s])
            rest = rest.replace(s, "")
    return found


def load_plans(year, plan_units, counties_by_state):
    """Individual (non-employer) plans with their service areas as sets of plan-unit FIPS codes.

    Returns {(contract, plan): {"type", "snp", "pace", "area": set(fips)}}.
    """
    z = M.pbp_zip(year)
    info = {}
    for r in M.zip_rows(z, "pbp_Section_A.txt"):
        if r["pbp_a_eghp_yn"] == "1":
            continue
        k = (r["pbp_a_hnumber"], r["pbp_a_plan_identifier"])
        info[k] = {"type": r["pbp_a_plan_type"], "snp": r["pbp_a_special_need_flag"] == "1",
                   "org": r["pbp_a_org_marketing_name"].strip(), "name": r["pbp_a_plan_name"].strip(),
                   "pace": r["pbp_a_plan_type"] == "20", "area": set()}
    ssa = M.ssa_fips()
    unmapped = set()
    for r in M.zip_rows(z, "PlanArea.txt"):
        k = (r["contract_id"], r["plan_id"])
        if k not in info or r["eghp_flag"] == "1":
            continue
        f = ssa.get(r["county_code"])
        if f is None:
            unmapped.add(r["county_code"])
            continue
        for g in AK_SPLIT.get(f, [f]):
            if g in plan_units:
                info[k]["area"].add(g)
    for r in M.zip_rows(z, "PlanRegionArea.txt"):
        k = (r["contract_id"], r["plan_id"])
        if k not in info or r["eghp_flag"] == "1":
            continue
        for st in region_states(r["region"]):
            info[k]["area"].update(counties_by_state.get(st, ()))
    plans = {k: v for k, v in info.items() if v["area"]}
    print(f"  CY{year}: {len(plans)} individual plans with a service area ({len(unmapped)} unmapped county codes)")
    return plans


def required(area, plan_units, lang, basis):
    pop = sum(plan_units[f]["pop5"] for f in area)
    x = sum(plan_units[f]["langs"][lang][basis] for f in area)
    return pop > 0 and x / pop >= THRESH, (x / pop if pop else 0)


def enrollment_fraction(plans, req, plan_units):
    """{fips: {lang/basis: share of individual MA+PDP members in plans that must translate}} for CY2026."""
    enroll, _, _ = M.enrollment(2026, "September")
    tot = defaultdict(float)
    hit = defaultdict(lambda: defaultdict(float))
    for k, by in enroll.items():
        if k not in plans or plans[k]["pace"]:
            continue
        for f, members in by.items():
            for g in AK_SPLIT.get(f, [f]):
                if g not in plan_units:
                    continue
                m = members / len(AK_SPLIT.get(f, [f]))
                tot[g] += m
                for key, ok in req[k].items():
                    if ok:
                        hit[g][key] += m
    return {f: {key: hit[f][key] / t for key in hit[f]} for f, t in tot.items() if t > 0}, sum(tot.values())


# ---------------------------------------------------------------------------

def main():
    global STATE_NAME
    counties, states, plan_units = load_acs()
    STATE_NAME = {f: s["name"] for f, s in states.items()}
    by_state = defaultdict(set)
    for f in plan_units:
        by_state[f[:2]].add(f)
    langs = list(LANGS)
    allk = langs + list(GROUPS)
    bases = ("lep", "all")
    total = {l: {b: sum(c["langs"][l][b] for c in counties.values()) for b in bases} for l in allk}
    pop5 = sum(c["pop5"] for c in counties.values())

    # --- county as plan (upper bound)
    coverage = []
    county_rows = []
    county_hits = {}
    for l in langs:
        for b in bases:
            cov, nareas, band_lo, band_hi = 0.0, 0, 0.0, 0.0
            for f, c in counties.items():
                lv = c["langs"][l]
                s = lv[b] / c["pop5"] if c["pop5"] else 0
                mo = share_moe(lv[b], lv[b + "_m"], c["pop5"], c["pop5_m"])
                if c["pop5"] >= FLOOR and s >= THRESH:
                    cov += lv["lep"]
                    nareas += 1
                    county_hits.setdefault((l, b), []).append(f)
                if c["pop5"] >= FLOOR and s - mo >= THRESH:
                    band_lo += lv["lep"]
                if c["pop5"] >= FLOOR and s + mo >= THRESH:
                    band_hi += lv["lep"]
            coverage.append({"language": l, "basis": b, "unit": "county", "lep_total": round(total[l]["lep"]),
                             "lep_covered": round(cov), "pct": round(100 * cov / total[l]["lep"], 1), "n_areas": nareas,
                             "pct_lo": round(100 * band_lo / total[l]["lep"], 1),
                             "pct_hi": round(100 * band_hi / total[l]["lep"], 1)})
    # small counties above the line, left out by the floor
    floor_left = []
    for l in langs[1:]:
        for b in bases:
            for f, c in counties.items():
                if c["pop5"] < FLOOR and c["pop5"] and c["langs"][l][b] / c["pop5"] >= THRESH:
                    floor_left.append({"county": f"{c['name']}, {c['state']}", "language": l, "basis": b,
                                       "pop5": round(c["pop5"]), "share": round(100 * c["langs"][l][b] / c["pop5"], 1),
                                       "lep": round(c["langs"][l]["lep"])})

    # --- state as plan
    for l in langs:
        for b in bases:
            cov, nareas = 0.0, 0
            for s in states.values():
                if s["langs"][l][b] / s["pop5"] >= THRESH:
                    cov += s["langs"][l]["lep"]
                    nareas += 1
            coverage.append({"language": l, "basis": b, "unit": "state", "lep_total": round(total[l]["lep"]),
                             "lep_covered": round(cov), "pct": round(100 * cov / total[l]["lep"], 1), "n_areas": nareas})
    state_rank = []
    for f, s in states.items():
        for l in langs:
            state_rank.append({"state": s["name"], "language": l, "lep_share": round(100 * s["langs"][l]["lep"] / s["pop5"], 2),
                               "all_share": round(100 * s["langs"][l]["all"] / s["pop5"], 2)})

    # --- real plan service areas, CY2027
    plans = load_plans(PLAN_YEAR, plan_units, by_state)
    req, pshare = {}, {}
    for k, p in plans.items():
        req[k], pshare[k] = {}, {}
        for l in allk:
            for b in bases:
                ok, s = required(p["area"], plan_units, l, b)
                req[k][f"{l}|{b}"] = ok
                pshare[k][f"{l}|{b}"] = s
    open_plans = defaultdict(list)  # county -> plans anyone with Medicare can join
    for k, p in plans.items():
        if p["snp"] or p["pace"]:
            continue
        for f in p["area"]:
            open_plans[f].append(k)
    plan_rows = []
    for l in allk:
        for b in bases:
            key = f"{l}|{b}"
            ks = [k for k in plans if req[k][key]]
            plan_rows.append({"language": l, "basis": b, "plans": len(ks),
                              "plans_open": sum(1 for k in ks if not plans[k]["snp"] and not plans[k]["pace"]),
                              "contracts": len({k[0] for k in ks}),
                              "contracts_no_pace": len({k[0] for k in ks if not plans[k]["pace"]}),
                              "ma_contracts": len({k[0] for k in ks if k[0][0] in "HR"}),
                              "pdp_contracts": len({k[0] for k in ks if k[0][0] == "S"})})
            if l in LANGS:
                cov = sum(plan_units[f]["langs"][l]["lep"] for f in plan_units
                          if any(req[k][key] for k in open_plans.get(f, ())))
                coverage.append({"language": l, "basis": b, "unit": "plans", "lep_total": round(total[l]["lep"]),
                                 "lep_covered": round(cov), "pct": round(100 * cov / total[l]["lep"], 1),
                                 "n_areas": sum(1 for k in ks if not plans[k]["snp"] and not plans[k]["pace"])})

    # --- enrollment weighted, CY2026 plans and September 2026 members
    plans26 = load_plans(2026, plan_units, by_state)
    req26 = {k: {f"{l}|{b}": required(p["area"], plan_units, l, b)[0] for l in langs for b in bases}
             for k, p in plans26.items()}
    frac, members = enrollment_fraction(plans26, req26, plan_units)
    for l in langs:
        for b in bases:
            key = f"{l}|{b}"
            num_ = sum(plan_units[f]["langs"][l]["lep"] * frac.get(f, {}).get(key, 0) for f in plan_units)
            coverage.append({"language": l, "basis": b, "unit": "enrolled", "lep_total": round(total[l]["lep"]),
                             "lep_covered": round(num_), "pct": round(100 * num_ / total[l]["lep"], 1), "n_areas": ""})

    # --- counties strip: every county (10k+) where a non-Spanish language reaches 3% on either basis
    def best_plan_share(f, key):
        ks = open_plans.get(f, ())
        return max((pshare[k][key] for k in ks), default=0)

    for f, c in counties.items():
        if c["pop5"] < FLOOR:
            continue
        for l in langs[1:]:
            lv = c["langs"][l]
            sl, sa = lv["lep"] / c["pop5"], lv["all"] / c["pop5"]
            if max(sl, sa) < 0.03:
                continue
            pf = f if not f.startswith("09") else None
            county_rows.append({
                "fips": f, "county": c["name"], "state": c["state"], "language": l,
                "pop5": round(c["pop5"]), "speakers": round(lv["all"]), "lep": round(lv["lep"]),
                "lep_share": round(100 * sl, 2), "lep_moe": round(100 * share_moe(lv["lep"], lv["lep_m"], c["pop5"], c["pop5_m"]), 2),
                "all_share": round(100 * sa, 2), "all_moe": round(100 * share_moe(lv["all"], lv["all_m"], c["pop5"], c["pop5_m"]), 2),
                "plans_open": len(open_plans.get(pf, ())) if pf else "",
                "plans_lep": sum(1 for k in open_plans.get(pf, ()) if req[k][f"{l}|lep"]) if pf else "",
                "plans_all": sum(1 for k in open_plans.get(pf, ()) if req[k][f"{l}|all"]) if pf else "",
                "best_plan_lep": round(100 * best_plan_share(pf, f"{l}|lep"), 2) if pf else "",
                "best_plan_all": round(100 * best_plan_share(pf, f"{l}|all"), 2) if pf else "",
            })
    county_rows.sort(key=lambda r: -max(r["lep_share"], r["all_share"]))

    # Native languages: C16001 lumps Navajo and Alaska Native languages into "Other and unspecified"
    other = "Other and unspecified"
    other_rows = []
    for f, c in counties.items():
        lv = c["langs"][other]
        if c["pop5"] < FLOOR or lv["lep"] / c["pop5"] < THRESH:
            continue
        ks = open_plans.get(f, ())
        other_rows.append({"county": c["name"], "state": c["state"], "pop5": round(c["pop5"]), "lep": round(lv["lep"]),
                           "lep_share": round(100 * lv["lep"] / c["pop5"], 1), "plans_open": len(ks),
                           "plans_lep": sum(1 for k in ks if req[k][f"{other}|lep"]),
                           "best_plan_lep": round(100 * max((pshare[k][f"{other}|lep"] for k in ks), default=0), 2)})
    other_rows.sort(key=lambda r: -r["lep_share"])

    # every non-Spanish plan requirement, for the record
    plan_list = []
    for k, p in plans.items():
        for l in allk:
            if l == "Spanish":
                continue
            for b in bases:
                if req[k][f"{l}|{b}"]:
                    sts = sorted({plan_units[f]["state"] for f in p["area"]})
                    plan_list.append({"contract": k[0], "plan": k[1], "org": p["org"], "plan_name": p["name"],
                                      "snp": "yes" if p["snp"] else "", "language": l, "basis": b,
                                      "share": round(100 * pshare[k][f"{l}|{b}"], 2), "counties": len(p["area"]),
                                      "states": " ".join(sts) if len(sts) <= 3 else f"{len(sts)} states"})
    plan_list.sort(key=lambda r: (r["language"], r["basis"], -r["share"]))

    # --- age: B16004 groups, share of all ages vs of 65+
    b4 = read_dat("b16004", ("0500000US", "0100000US"))
    grp = {"Spanish": 4, "Other Indo-European": 9, "Asian and Pacific Island": 14, "Other": 19}
    age_rows, senior = [], {}

    def lep_of(r, start):  # "well" + "not well" + "not at all" = less than very well
        return sum(n(r[f"B16004_E{start + i:03d}"]) for i in (2, 3, 4))

    county_age = {}
    for gid, r in b4.items():
        if gid.startswith("0500000US72"):
            continue
        tot_all, tot_65 = n(r["B16004_E001"]), n(r["B16004_E046"])
        d = {"tot_all": tot_all, "tot_65": tot_65}
        for g, s in grp.items():
            d[g] = {"all": sum(lep_of(r, s + off) for off in (0, 22, 44)), "65": lep_of(r, s + 44)}
        county_age[gid] = d
    us = county_age.pop("0100000US")
    for g in grp:
        senior[g] = round(us[g]["65"])
    # national check: Asian/PI LEP seniors living where the group passes 5% (all ages vs 65+)
    g = "Asian and Pacific Island"
    tot65 = sum(d[g]["65"] for d in county_age.values())
    pass_all = sum(d[g]["65"] for d in county_age.values() if d["tot_all"] >= FLOOR and d[g]["all"] / d["tot_all"] >= THRESH)
    pass_65 = sum(d[g]["65"] for d in county_age.values() if d["tot_all"] >= FLOOR and d["tot_65"] and d[g]["65"] / d["tot_65"] >= THRESH)
    names = geo_names()
    top = sorted(county_age.items(), key=lambda kv: -kv[1][g]["65"])[:6]
    for gid, d in top:
        for gg in ("Asian and Pacific Island", "Spanish"):
            age_rows.append({"fips": gid[9:], "county": names.get(gid, gid).split(",")[0],
                             "state": names.get(gid, gid).split(", ")[-1], "group": gg,
                             "share_all_ages": round(100 * d[gg]["all"] / d["tot_all"], 1),
                             "share_65plus": round(100 * d[gg]["65"] / d["tot_65"], 1),
                             "lep_65plus": round(d[gg]["65"])})

    # --- your language: B16001 detailed languages, state and PUMA
    b1 = read_dat("b16001", ("0400000US", "795P200US", "0100000US"))
    shells = {}
    with open(V.fetch(SHELLS), encoding="latin-1") as fh:
        for line in fh:
            p = line.split("|")
            if len(p) > 4 and p[0] == "B16001" and p[4].endswith(":") and p[3] != "B16001_001":
                shells[int(p[3][-3:])] = p[4].rstrip(":")
    single = {i: lab for i, lab in shells.items()
              if not lab.lower().startswith("other") and " or " not in lab and "," not in lab.replace("(incl.", "(")}
    # keep labels like "Chinese (incl. Mandarin, Cantonese)" and "Persian (incl. Farsi, Dari)"
    for i, lab in shells.items():
        if "(incl." in lab and not lab.lower().startswith("other"):
            single[i] = lab
    # In neighborhoods (PUMAs) of Arizona, New Mexico and Utah where Navajo speakers with limited English
    # are 5%+ of residents: Navajo's share of all limited-English speakers of languages other than English/Spanish
    nav_lep = oth_lep = 0.0
    nav_pumas = 0
    for gid, r in b1.items():
        if gid[:11] not in ("795P200US04", "795P200US35", "795P200US49"):
            continue
        p = n(r["B16001_E001"])
        if p and n(r["B16001_E122"]) / p >= THRESH:
            nav_pumas += 1
            nav_lep += n(r["B16001_E122"])
            oth_lep += sum(n(r[f"B16001_E{i + 2:03d}"]) for i in range(6, 127, 3))
    navajo = {"pumas": nav_pumas, "navajo_lep": round(nav_lep), "pct_of_non_spanish_lep": round(100 * nav_lep / oth_lep, 1)}
    fl = b1["0400000US12"]
    checks = {
        "c16001_lep_all_languages": round(sum(c["langs"][k]["lep"] for c in counties.values() for k in allk)),
        "b16004_lep_all_languages": round(sum(us[gg]["all"] for gg in grp)),
        "fl_bengali_speakers": round(n(fl["B16001_E057"])), "fl_bengali_lep": round(n(fl["B16001_E059"])),
    }
    lang_rows = []
    st_rows = {g: r for g, r in b1.items() if g.startswith("0400000US") and g[9:11] != "72"}
    pu_rows = {g: r for g, r in b1.items() if g.startswith("795P200US") and g[9:11] != "72"}
    for i, lab in sorted(single.items()):
        def vals(r):
            p = n(r["B16001_E001"])
            return p, n(r[f"B16001_E{i:03d}"]), n(r[f"B16001_E{i + 2:03d}"])
        lep_tot = sum(vals(r)[2] for r in st_rows.values())
        all_tot = sum(vals(r)[1] for r in st_rows.values())
        if lep_tot < 20000:
            continue
        row = {"language": lab.replace(" (incl. ", " (").replace("Filipino)", "Filipino)"), "lep_total": round(lep_tot),
               "speakers_total": round(all_tot)}
        for unit, rows_ in (("state", st_rows), ("puma", pu_rows)):
            for b, j in (("lep", 2), ("all", 1)):
                cov, best, bestname = 0.0, 0.0, ""
                for gid, r in rows_.items():
                    p, a, le = vals(r)
                    s = (le if j == 2 else a) / p if p else 0
                    if s >= THRESH:
                        cov += le
                    if s > best:
                        best, bestname = s, names.get(gid, gid)
                row[f"{unit}_{b}_pct"] = round(100 * cov / lep_tot, 1) if lep_tot else 0
                row[f"{unit}_{b}_best"] = round(100 * best, 2)
                row[f"{unit}_{b}_best_name"] = bestname.replace(" PUMA;", ",").replace(" PUMA", "")
        # approximate OCR top-15 notice: rank among single-language lines by state LEP count
        top15 = 0.0
        for gid, r in st_rows.items():
            ranks = sorted(single, key=lambda k: -n(r[f"B16001_E{k + 2:03d}"]))[:15]
            if i in ranks:
                top15 += n(r[f"B16001_E{i + 2:03d}"])
        row["top15_pct"] = round(100 * top15 / lep_tot, 1)
        lang_rows.append(row)
    lang_rows.sort(key=lambda r: -r["lep_total"])

    # Hawaii: the one grouped C16001 category that crosses the line on CMS's method.
    # Which detailed B16001 languages make it up, and which 2027 plans it puts over 5%.
    oap = "Other Asian and Pacific Island languages"
    hi_c, hi_b = states["15"], b1["0400000US15"]
    hi_det = {lab: n(hi_b[f"B16001_E{i + 2:03d}"]) for i, lab in shells.items()}
    hi_keys = [k for k in plans if req[k][f"{oap}|lep"]]
    hawaii = {
        "state_lep_share": round(100 * hi_c["langs"][oap]["lep"] / hi_c["pop5"], 2),
        "state_all_share": round(100 * hi_c["langs"][oap]["all"] / hi_c["pop5"], 2),
        "group_lep": round(hi_c["langs"][oap]["lep"]),
        "austronesian_lep": round(hi_det["Ilocano, Samoan, Hawaiian, or other Austronesian languages"]),
        "japanese_lep": round(hi_det["Japanese"]),
        "plans": len(hi_keys),
        "plans_open": sum(1 for k in hi_keys if not plans[k]["snp"] and not plans[k]["pace"]),
        "pdp_plans": sum(1 for k in hi_keys if k[0][0] == "S"),
        "all_in_hawaii": all({plan_units[f]["state"] for f in plans[k]["area"]} == {"Hawaii"} for k in hi_keys),
        "share_min": round(100 * min(pshare[k][f"{oap}|lep"] for k in hi_keys), 2),
        "share_max": round(100 * max(pshare[k][f"{oap}|lep"] for k in hi_keys), 2),
    }

    # --- headline numbers
    cv = {(r["language"], r["basis"], r["unit"]): r for r in coverage}
    nonsp = langs[1:]
    lep_nonsp = sum(total[l]["lep"] for l in nonsp)
    summary = {
        "acs": "ACS 2020-2024 5-year estimates",
        "plan_year": PLAN_YEAR,
        "floor": FLOOR,
        "counties": len(counties),
        "pop5": round(pop5),
        "plans_individual": len(plans),
        "plans_open": sum(1 for p in plans.values() if not p["snp"] and not p["pace"]),
        "members_2026": round(members),
        "lep_total": {l: round(total[l]["lep"]) for l in langs},
        "speakers_total": {l: round(total[l]["all"]) for l in langs},
        "nonspanish_lep_total": round(lep_nonsp),
        "nonspanish_covered": {f"{b}|{u}": round(sum(cv[(l, b, u)]["lep_covered"] for l in nonsp))
                               for b in bases for u in ("county", "plans", "enrolled", "state")},
        "county_hits": {f"{l}|{b}": [f"{counties[f]['name']}, {counties[f]['state']}" for f in fs]
                        for (l, b), fs in county_hits.items() if l != "Spanish"},
        "floor_left_out": floor_left,
        "senior_lep_65": senior,
        "senior_lep_65_total": round(sum(senior.values())),
        "asianpi_seniors": {"total": round(tot65), "pct_pass_all_ages": round(100 * pass_all / tot65, 1),
                            "pct_pass_65plus": round(100 * pass_65 / tot65, 1)},
        "state_top": sorted(state_rank, key=lambda r: -r["lep_share"]),
        "groups_2027": {f"{r['language']}|{r['basis']}": r for r in plan_rows if r["language"] in GROUPS},
        "other_lang_counties": other_rows,
        "checks": checks,
        "navajo_pumas": navajo,
        "hawaii_group": hawaii,
    }
    summary["state_top"] = [r for r in summary["state_top"] if r["language"] != "Spanish"][:6] + \
        [r for r in summary["state_top"] if r["language"] == "Spanish" and r["lep_share"] >= 5]

    V.write_csv(OUT / "coverage.csv", coverage, ["language", "basis", "unit", "lep_total", "lep_covered", "pct",
                                                 "n_areas", "pct_lo", "pct_hi"])
    V.write_csv(OUT / "counties.csv", county_rows, list(county_rows[0]))
    V.write_csv(OUT / "age.csv", age_rows, list(age_rows[0]))
    V.write_csv(OUT / "languages.csv", lang_rows, list(lang_rows[0]))
    V.write_csv(OUT / "plans.csv", plan_rows, list(plan_rows[0]))
    V.write_csv(OUT / "plan_list.csv", plan_list, list(plan_list[0]))
    (OUT / "policy.json").write_text(json.dumps(POLICY, indent=1))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    for r in coverage:
        print(f"  {r['language']:11s} {r['basis']:4s} {r['unit']:9s} {r['pct']:5.1f}%  ({r['n_areas']})")
    for r in plan_rows:
        print("  plans", r)


FR = "https://www.federalregister.gov/documents/"
POLICY = {"checked": "2026-11-12", "events": [
    {"date": "2011-07-15", "title": "CMS spells out the method",
     "text": "An HPMS memo to plans tells them to divide the people 5 and older who speak a language and speak English less than \"very well\" by everyone 5 and older in the plan's counties or states. At 5% or more, the plan must translate.",
     "url": "https://www.cms.gov/medicare/prescription-drug-coverage/prescriptiondrugcovcontra/downloads/update2012translatedmaterialsrequirementsandresourcesfinalhpmsmemo_071511.pdf",
     "src": "CMS HPMS memo, Appendix A"},
    {"date": "2023-04-12", "title": "CMS counts contracts, not people",
     "text": "For 2023, CMS wrote, 16 Medicare Advantage contracts met the line for Chinese and 19 Medicare Advantage and drug plans for \"other Asian languages\", and no service area met it for any other language besides Spanish.",
     "url": "https://www.federalregister.gov/documents/2023/04/12/2023-07115/", "src": "88 FR 22120, at 22227"},
    {"date": "2024-05-06", "title": "Civil-rights notice in 15 languages",
     "text": "HHS's Office for Civil Rights requires a notice, in at least the 15 languages most common among people with limited English in the state, that free language help is available (45 CFR 92.11).",
     "url": FR + "2024/05/06/2024-08711/", "src": "89 FR 37522"},
    {"date": "2025-09-30", "title": "CMS stops translating its model documents",
     "text": "CMS translated its model coverage documents into Spanish, Chinese, Korean and Vietnamese for 2026, then wrote: \"Beginning with CY 2027, CMS will provide model materials in English only.\"",
     "url": "https://clearpolappstorage.blob.core.windows.net/media/docs/user_1/document_124496/Contract%20Year%202026%20Translated%20Model%20Materials%20Requirements%20and%20Language%20Data%20Analysis_Memo.pdf",
     "src": "CMS memo, CY2026 translated model materials"},
    {"date": "2025-11-28", "title": "The 5% rule is on the table",
     "text": "The proposed 2027 rule asks for comment on \"Modifying the 5 percent translation requirement\", in a list of ideas for reducing burden on plans, and proposes dropping CMS's own notice of language help.",
     "url": FR + "2025/11/28/2025-21456/", "src": "90 FR 54894, at 54897"},
    {"date": "2026-01-26", "title": "Advocates push back",
     "text": "Justice in Aging asks CMS not to weaken the rule and to trigger translation at 5% or 1,000 people, whichever is lower, writing that the 5% trigger \"neglects many substantial non-English speaking communities\".",
     "url": "https://justiceinaging.org/wp-content/uploads/2026/01/Justice-in-Aging-Medicare-Advantage-2027-rule-comment.pdf",
     "src": "Justice in Aging comment"},
    {"date": "2026-04-06", "title": "CMS's language notice is rescinded",
     "text": "The final 2027 rule removes CMS's own notice of language help (42 CFR 422.2267(e)(31) now reads \"[Reserved]\"), leaving OCR's 15-language notice. The 5% translation rule itself is unchanged.",
     "url": FR + "2026/04/06/2026-06600/", "src": "91 FR 17384"},
    {"date": "2026-11-09", "title": "Still the rule",
     "text": "The eCFR, current to this date, still sets the line at \"at least 5 percent of the individuals in a plan benefit package (PBP) service area\".",
     "url": "https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-B/part-422/subpart-V/section-422.2267",
     "src": "eCFR 42 CFR 422.2267(a)(2)"},
]}

STATE_NAME = {}
if __name__ == "__main__":
    main()
