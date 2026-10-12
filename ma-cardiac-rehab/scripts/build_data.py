"""Build the Medicare Advantage cardiac rehab cost data.

For every individual Medicare Advantage plan (and segment) in 2026 and 2027, read the
in-network cost sharing for Medicare-covered cardiac rehabilitation (CR) and intensive
cardiac rehabilitation (ICR) from the CMS Plan Benefit Package files (section B3), and
price a full course: 36 sessions of CR or 72 sessions of ICR, capped at the plan's
in-network out-of-pocket maximum. Coinsurance is priced at the 2026 national hospital
outpatient rate for a session (APC 5771, which pays CR and ICR alike).

Counties are summarized over the people actually enrolled (CMS enrollment by plan and
county, September 2026). For 2027, each member is followed to the plan the CMS plan
crosswalk moves them into; members whose plan ends in their county are left out of
the 2027 costs and counted separately.

Writes _src/data/counties.csv and _src/data/summary.json. The published page is
password-protected: after building, encrypt _src/ into index.html with
  python3 _viz/encrypt_page.py ma-cardiac-rehab
Usage: python3 ma-cardiac-rehab/scripts/build_data.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_src" / "data"  # the page is password-protected: plaintext stays in _src/ (git-ignored)
sys.path.insert(0, str(ROOT.parent / "_viz"))
import malib as M  # noqa: E402

# CY2026 OPPS Addendum A (October 2026): APC 5771 Cardiac Rehabilitation, which covers
# CPT 93797/93798 and HCPCS G0422/G0423, pays $131.70 with a $26.34 (20%) copayment.
SESSION_RATE = 131.70
TM_COPAY = 26.34
SESSIONS = {"cr": 36, "icr": 72}  # standard CR course; ICR allows up to 72 one-hour sessions
BIT = {"cr": 1, "icr": 2}  # positions in pbp_b3_copay_ehc / pbp_b3_coins_ehc
YEARS = (2026, 2027)
ENROLL = (2026, "September")
DSNP = "Dual-eligible special needs plans"
HIST = [("$0", 0), ("$1-10", 10), ("$11-20", 20), ("$21-26", TM_COPAY), ("$27-35", 35), ("$36-45", 45), ("Over $45", 1e9)]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def benefits(year):
    """{(contract, plan, segment): {cr, icr (per-session $), auth, refer, moop}}"""
    moop = {}
    for r in M.zip_rows(M.pbp_zip(year), "pbp_Section_D.txt"):
        v = num(r.get("pbp_d_out_pocket_amt"))
        moop[(r["pbp_a_hnumber"], r["pbp_a_plan_identifier"], r["segment_id"])] = v
    out, odd = {}, 0
    for r in M.pbp_table(year, "pbp_b3_cardiac_rehab"):
        k = (r["pbp_a_hnumber"], r["pbp_a_plan_identifier"], r["segment_id"])
        b = {"auth": r["pbp_b3_auth_yn"] == "1", "refer": r["pbp_b3_refer_yn"] == "1", "moop": moop.get(k)}
        for svc, i in BIT.items():
            copay = r["pbp_b3_copay_yn"] in ("1", "3") and r["pbp_b3_copay_ehc"][i:i + 1] == "1"
            coins = r["pbp_b3_coins_yn"] in ("1", "3") and r["pbp_b3_coins_ehc"][i:i + 1] == "1"
            odd += copay and coins
            cost = 0.0
            if copay:  # a range means cost sharing differs by setting; take the higher (usually hospital outpatient)
                cost += num(r[f"pbp_b3_copay_amt_mc_max_{svc}s"]) or num(r[f"pbp_b3_copay_amt_mc_min_{svc}s"]) or 0
            if coins:
                pct = num(r[f"pbp_b3_coins_pct_mc_max_{svc}s"]) or num(r[f"pbp_b3_coins_pct_mc_min_{svc}s"]) or 0
                cost += SESSION_RATE * pct / 100
            b[svc] = round(cost, 2)
            b[svc + "_kind"] = "coins" if coins and not copay else "copay"
        out[k] = b
    print(f"{year}: {len(out)} plan segments with B3 data ({odd} service rows with both a copay and coinsurance)")
    return out


def course(b, svc):
    c = b[svc] * SESSIONS[svc]
    return min(c, b["moop"]) if b["moop"] else c


def main():
    plans = {y: M.plans(y) for y in YEARS}
    area = {y: M.plan_area(y, set(plans[y])) for y in YEARS}
    ben = {y: benefits(y) for y in YEARS}
    enroll, fips_of, contracts = M.enrollment(*ENROLL)
    xwalk = M.crosswalk(2027)
    ssa_of = {}  # FIPS -> SSA (PlanArea is keyed by SSA county codes)
    for ssa, f in fips_of.items():
        ssa_of.setdefault(f, ssa)

    def segment(year, k, ssa):
        return area[year].get(k, {}).get(ssa, "0")

    # Plans offered in each county (PlanArea, which leaves out regional PPOs)
    offered = {y: defaultdict(set) for y in YEARS}
    for y in YEARS:
        for k, counties in area[y].items():
            for ssa, seg in counties.items():
                if ssa in fips_of:
                    offered[y][fips_of[ssa]].add((*k, seg))

    def kind(p):
        return {"Dual-eligible": DSNP, "": "Plans open to anyone"}.get(
            p["snp"], "Chronic-condition and institutional special needs plans")

    # Member-level records: year -> fips -> [(members, benefit, parent, plan kind)]
    rec = {y: defaultdict(list) for y in YEARS}
    ending = defaultdict(int)  # members whose plan ends in their county for 2027
    total = defaultdict(int)
    for k, counties in enroll.items():
        if k not in plans[2026]:
            continue
        parent = M.parent_name(contracts.get(k, {}).get("parent", ""))
        dests = [d for _, d in xwalk.get(k, []) if d]
        for fips, n in counties.items():
            total[fips] += n
            ssa = ssa_of.get(fips)
            b = ben[2026].get((*k, segment(2026, k, ssa)))
            if b:
                rec[2026][fips].append((n, b, parent, kind(plans[2026][k])))
            # 2027: the crosswalk destination that serves this county (regional PPOs serve whole regions)
            d = next((d for d in dests if d in plans[2027] and (ssa in area[2027].get(d, {}) or d[0].startswith("R"))), None)
            if d is None:
                ending[fips] += n
                continue
            b27 = ben[2027].get((*d, segment(2027, d, ssa)))
            if b27:
                rec[2027][fips].append((n, b27, parent, kind(plans[2027][d])))

    def summarize(rs, dsnp_costs=False):
        """Member-weighted figures. Costs leave out dual-eligible SNP members unless asked:
        Medicaid usually pays their Medicare cost sharing, so plan copays don't reach them."""
        s = {}
        if not rs:
            return s
        s["pct_auth"] = round(100 * sum(m for m, b, *_ in rs if b["auth"]) / sum(r[0] for r in rs), 1)
        s["members"] = sum(r[0] for r in rs)
        rs = rs if dsnp_costs else [r for r in rs if r[3] != DSNP]
        n = sum(r[0] for r in rs)
        s["cost_members"] = n
        if not n:
            return s
        for svc in SESSIONS:
            s[f"{svc}_session"] = round(sum(m * b[svc] for m, b, *_ in rs) / n, 2)
            s[f"{svc}_course"] = round(sum(m * course(b, svc) for m, b, *_ in rs) / n)
            s[f"pct_above_tm_{svc}"] = round(100 * sum(m for m, b, *_ in rs if b[svc] > TM_COPAY + 0.005) / n, 1)
            s[f"pct_zero_{svc}"] = round(100 * sum(m for m, b, *_ in rs if b[svc] == 0) / n, 1)
        return s

    counties = []
    for fips in sorted(total):
        if fips[:2] not in M.V.STATE_FIPS:
            continue
        row = {"fips": fips, "ma_members": total[fips],
               "pct_plan_ending": round(100 * ending[fips] / total[fips], 1) if total[fips] else ""}
        for y in YEARS:
            s = summarize(rec[y][fips])
            for key in ("cr_session", "icr_session", "cr_course", "icr_course", "pct_above_tm_cr", "pct_above_tm_icr", "pct_auth"):
                row[f"{key}_{y}"] = s.get(key, "")
            # range of course costs among plans anyone in the county could join that year (not SNPs)
            opts = [ben[y][p] for p in offered[y].get(fips, ()) if p in ben[y] and not plans[y][p[:2]]["snp"]]
            row[f"plans_{y}"] = len(opts)
            row[f"cr_course_min_{y}"] = round(min(course(b, "cr") for b in opts)) if opts else ""
            row[f"cr_course_max_{y}"] = round(max(course(b, "cr") for b in opts)) if opts else ""
        counties.append(row)

    # National summary and insurer table
    summary = {"tm_copay": TM_COPAY, "session_rate": SESSION_RATE, "sessions": SESSIONS,
               "tm_course": {svc: round(TM_COPAY * n) for svc, n in SESSIONS.items()},
               "enrollment_month": f"{ENROLL[1]} {ENROLL[0]}", "years": {}}
    for y in YEARS:
        allr = [r for fips in rec[y] if fips[:2] in M.V.STATE_FIPS for r in rec[y][fips]]
        s = summarize(allr)
        costr, cn = [r for r in allr if r[3] != DSNP], s["cost_members"]
        # distribution of per-session cost (share of members); one edge sits at traditional Medicare's copay
        for svc in SESSIONS:
            counts = [0] * len(HIST)
            for m, b, *_ in costr:
                counts[next(i for i, (_, hi) in enumerate(HIST) if b[svc] <= hi + 0.005)] += m
            s[f"{svc}_hist"] = [{"label": lab, "pct": round(100 * c / cn, 1), "above_tm": hi > TM_COPAY}
                                for (lab, hi), c in zip(HIST, counts)]
        # ICR costs more than CR in the same plan
        s["pct_icr_gt_cr"] = round(100 * sum(m for m, b, *_ in costr if b["icr"] > b["cr"] + 0.005) / cn, 1)
        s["pct_course_over_1000_icr"] = round(100 * sum(m for m, b, *_ in costr if course(b, "icr") > 1000) / cn, 1)
        s["pct_course_over_tm_icr"] = round(100 * sum(m for m, b, *_ in costr if course(b, "icr") > TM_COPAY * 72 + 1) / cn, 1)
        by = defaultdict(list)
        for r in allr:
            by[r[2]].append(r)
        top = sorted(by, key=lambda p: -sum(r[0] for r in by[p]))[:10]
        s["insurers"] = [{"name": p, **{k: v for k, v in summarize(by[p]).items()
                                         if k in ("members", "cr_session", "icr_session", "cr_course", "icr_course", "pct_auth", "pct_above_tm_cr")}}
                         for p in top]
        bykind = defaultdict(list)
        for r in allr:
            bykind[r[3]].append(r)
        s["kinds"] = [{"name": kn, **{k: v for k, v in summarize(bykind[kn], dsnp_costs=True).items()
                                     if k in ("members", "cr_session", "icr_session", "pct_zero_cr", "pct_above_tm_cr", "pct_auth")}}
                      for kn in ("Plans open to anyone", "Dual-eligible special needs plans",
                                 "Chronic-condition and institutional special needs plans")]
        s["plans"] = len({k for k in ben[y] if k[:2] in plans[y]})
        summary["years"][str(y)] = s
    summary["members_plan_ending"] = sum(v for f, v in ending.items() if f[:2] in M.V.STATE_FIPS)
    summary["members_total"] = sum(v for f, v in total.items() if f[:2] in M.V.STATE_FIPS)
    print(json.dumps({k: v for k, v in summary.items() if k != "years"}, indent=2))
    for y in YEARS:
        print(y, {k: v for k, v in summary["years"][str(y)].items() if not k.endswith("hist") and k != "insurers"})

    cols = list(counties[0].keys())
    OUT.mkdir(parents=True, exist_ok=True)
    M.V.write_csv(OUT / "counties.csv", counties, cols)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")


if __name__ == "__main__":
    main()
