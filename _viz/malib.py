"""Shared helpers for the Medicare Advantage pages (ma-cardiac-rehab, ma-network-standards, ma-plan-exits).

CMS public files, all cached under _viz/cache/ by vizlib.fetch:
  - PBP Benefits (plan benefit packages), one zip per contract year: tab-delimited
    tables per benefit section plus PlanArea.txt (the counties each plan/segment serves).
  - Plan Crosswalk, one zip per contract year: where each previous-year plan's
    members go (renewal, consolidation, termination, service area reduction).
  - Monthly Enrollment by Contract/Plan/State/County (CPSC): enrollment per plan and
    county; counts of 1-10 are suppressed ("*") and treated as 0 here.
  - HSD Reference File: network adequacy county designations and time/distance limits.

County codes: CMS files key counties by SSA code; the CPSC file carries the matching
FIPS code for every county with enrollment, which is used to translate. Alaska's
legacy SSA/FIPS codes are mapped onto the current boroughs used by the county map.
"""
import csv
import io
import json
import zipfile
from collections import defaultdict

import vizlib as V

CMS = "https://www.cms.gov/files/zip/"
PBP = CMS + "pbp-benefits-{year}.zip"
CROSSWALK = CMS + "plan-crosswalk-{year}.zip"
CPSC = CMS + "monthly-enrollment-cpsc-{month}-{year}.zip"
HSD = "https://www.cms.gov/files/document/2026-hsd-reference-file-updated-12-17-2025.xlsx"

# Medicare Advantage plan types kept (PBP pbp_a_plan_type): HMO, HMO-POS, local PPO,
# PSO, PFFS, regional PPO. Left out: PACE, cost plans, MSAs and drug-only plans.
MA_TYPES = {"01": "HMO", "02": "HMO-POS", "04": "Local PPO", "05": "PSO", "09": "PFFS", "31": "Regional PPO"}

# Legacy Alaska county codes in CMS files -> current borough FIPS on the county map
AK_FIX = {"02270": "02158", "02201": "02198", "02280": "02275", "02232": "02105", "02030": "02105",
          "02040": "02185", "02120": "02122", "02250": "02290", "02080": "02261", "02230": "02282"}


def zip_rows(path, member, delimiter="\t"):
    """Rows of a delimited text member inside a zip, as dicts (CMS files are Latin-1)."""
    with zipfile.ZipFile(path) as z, z.open(member) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "latin-1", newline=""), delimiter=delimiter)


def pbp_zip(year):
    return V.fetch(PBP.format(year=year))


def pbp_table(year, name):
    """One PBP benefits table, e.g. pbp_table(2027, "pbp_b3_cardiac_rehab")."""
    return list(zip_rows(pbp_zip(year), name + ".txt"))


def plan_key(r):
    return r["pbp_a_hnumber"], r["pbp_a_plan_identifier"]


def plans(year):
    """Section A: {(contract, plan): info} for individual (non-employer) MA plans, all segments."""
    out = {}
    for r in zip_rows(pbp_zip(year), "pbp_Section_A.txt"):
        if r["pbp_a_plan_type"] not in MA_TYPES or r["pbp_a_eghp_yn"] == "1":
            continue
        out[plan_key(r)] = {
            "contract": r["pbp_a_hnumber"], "plan": r["pbp_a_plan_identifier"],
            "name": r["pbp_a_plan_name"].strip(), "org": r["pbp_a_org_marketing_name"].strip(),
            "type": MA_TYPES[r["pbp_a_plan_type"]],
            "snp": {"1": "Institutional", "3": "Dual-eligible", "4": "Chronic condition"}.get(r["pbp_a_special_need_plan_type"], "")
            if r["pbp_a_special_need_flag"] == "1" else "",
        }
    return out


def plan_area(year, keep=None):
    """{(contract, plan): {ssa_county: segment_id}} from the PBP PlanArea file."""
    out = defaultdict(dict)
    for r in zip_rows(pbp_zip(year), "PlanArea.txt"):
        k = (r["contract_id"], r["plan_id"])
        if keep is not None and k not in keep:
            continue
        out[k][r["county_code"]] = r["segment_id"]
    return dict(out)


def crosswalk(year):
    """Plan crosswalk into `year`: {(prev contract, prev plan): [(status, (cur contract, cur plan) | None)]}."""
    z = V.fetch(CROSSWALK.format(year=year))
    with zipfile.ZipFile(z) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
    out = defaultdict(list)
    for r in zip_rows(z, member):
        if r["PREVIOUS_PLAN_ID"] == "NEW":
            continue
        cur = None if r["CURRENT_CONTRACT_ID"] == "TERMINATED" else (r["CURRENT_CONTRACT_ID"], r["CURRENT_PLAN_ID"])
        out[(r["PREVIOUS_CONTRACT_ID"], r["PREVIOUS_PLAN_ID"])].append((r["STATUS"], cur))
    return dict(out)


def enrollment(year, month):
    """CPSC enrollment for one month.

    Returns (enroll, ssa_to_fips, contracts):
      enroll: {(contract, plan): {fips: members}} (suppressed cells counted as 0)
      ssa_to_fips: {ssa: fips} for every county that appears with a FIPS code
      contracts: {(contract, plan): {parent, org, plan_type, snp, eghp}}
    """
    z = V.fetch(CPSC.format(month=month.lower(), year=year))
    folder = f"CPSC_Enrollment_{year}_{MONTHS.index(month.lower()) + 1:02d}/"
    enroll, ssa = defaultdict(dict), {}
    for r in zip_rows(z, folder + f"CPSC_Enrollment_Info_{year}_{MONTHS.index(month.lower()) + 1:02d}.csv", ","):
        fips = r["FIPS State County Code"]
        if not fips:
            continue
        fips = AK_FIX.get(fips, fips)
        ssa[r["SSA State County Code"]] = fips
        n = r["Enrollment"]
        if n and n != "*":
            k = (r["Contract Number"], r["Plan ID"].zfill(3))
            enroll[k][fips] = enroll[k].get(fips, 0) + int(n)
    contracts = {}
    for r in zip_rows(z, folder + f"CPSC_Contract_Info_{year}_{MONTHS.index(month.lower()) + 1:02d}.csv", ","):
        contracts[(r["Contract ID"], r["Plan ID"].zfill(3))] = {
            "parent": r["Parent Organization"].strip(), "org": r["Organization Marketing Name"].strip(),
            "plan_type": r["Plan Type"], "snp": r["SNP Plan"] == "Yes", "eghp": r["EGHP"] == "Yes"}
    return dict(enroll), ssa, contracts


def hsd_limits():
    """Network adequacy limits from the HSD Reference File.

    Returns {ssa: {"county", "st", "designation", "limits": {specialty: (max minutes, max miles)}}},
    reading both the provider and the facility time & distance sheets.
    """
    import openpyxl  # only this helper needs it
    wb = openpyxl.load_workbook(V.fetch(HSD, "hsd-2026.xlsx"), read_only=True, data_only=True)
    out = {}
    for sheet in ("Provider Time & Distance", "Facility Time & Distance"):
        rows = list(wb[sheet].iter_rows(values_only=True))
        names, kinds = rows[1], rows[3]
        cols = [(i, " ".join(str(names[i]).replace("(see Notes)", "").replace("(See Notes)", "").split()))
                for i in range(5, len(names)) if names[i] and kinds[i] == "Time"]
        for r in rows[4:]:
            if not r[3]:
                continue
            ssa = str(r[3]).zfill(5)
            c = out.setdefault(ssa, {"county": r[0], "st": r[1], "designation": r[4], "limits": {}})
            for i, name in cols:
                if isinstance(r[i], (int, float)):
                    c["limits"][name] = (r[i], r[i + 1])
    return out


def ssa_fips(year=2026, month="September"):
    """{ssa: fips} from a CPSC enrollment file, cached as JSON (the full file is large to parse)."""
    path = V.CACHE / f"ssa_fips_{year}_{month.lower()}.json"
    if not path.exists():
        path.write_text(json.dumps(enrollment(year, month)[1]))
    return json.loads(path.read_text())


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def parent_name(p):
    """Short display names for the largest parent organizations."""
    for k, v in [("UnitedHealth", "UnitedHealthcare"), ("Humana", "Humana"), ("CVS", "Aetna (CVS)"),
                 ("Elevance", "Elevance (Anthem)"), ("Centene", "Wellcare (Centene)"), ("Kaiser", "Kaiser Permanente"),
                 ("Cigna", "Cigna"), ("HCSC", "HCSC (Blue Cross)"), ("Health Care Service", "HCSC (Blue Cross)"),
                 ("Molina", "Molina"), ("Highmark", "Highmark"), ("Devoted", "Devoted Health"),
                 ("Alignment", "Alignment Health"), ("SCAN", "SCAN"), ("Clover", "Clover Health")]:
        if k.lower() in p.lower():
            return v
    return p
