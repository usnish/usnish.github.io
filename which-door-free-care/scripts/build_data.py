"""Build the data for "Which door?": free-care income lines at nonprofit ERs, county by county.

What it does
1. Pulls every IRS Form 990 Schedule H from the IRS e-file bulk releases of 2024,
   2025 and 2026 (irs_scan.py) and keeps each filer's latest tax year.
2. Links each Part V Section B policy block to the hospital facilities it covers
   (Section A), and reads line 13: "FPG family income limit for eligibility for
   free care" (a percent of the federal poverty guidelines).
3. Keeps general medical-surgical hospitals with a 24-hour emergency room (drops
   children's, psychiatric, rehab, cancer and other specialty filers), checks them
   against CMS's Hospital General Information file, and places each in a county
   with the Census geocoder. A blank Schedule H ER box is overridden when CMS lists
   the same hospital with emergency services. Adds the campuses of multi-campus
   licenses (CAMPUSES), drops closed, superseded, stale and for-profit-operated
   facilities, and lists ER hospitals that report no usable line by county.
4. Applies state free-care floors (effective line = max(reported line, floor)); where a
   spot check of a posted policy found a different line (FAP_CHECKS), the posted line is used.
5. Joins ACS 2020-2024 5-year table C27016 (uninsured by ratio of income to
   poverty, by age) and counts uninsured people under 65 in each county whose
   income sits between the county's stingiest and most generous nonprofit ER.

Writes data/facilities.csv, data/counties.csv, data/floors.csv, data/summary.json.
Usage: python3 which-door-free-care/scripts/build_data.py   (Python 3 standard library only)
"""
import csv
import io
import json
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import irs_scan  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
OUT = HERE / "data"
CACHE = ROOT / "_viz" / "cache" / "which_door"
LOG = CACHE / "build_log.txt"
UA = irs_scan.UA

ACS_URL = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-{t}.dat"
ACS_GEOS = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/documentation/Geos20245YR.txt"
ZCTA_COUNTY = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
CT_TOWNS = "https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.txt"
RUCC = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv?v=41138"
CMS_HGI = ROOT / "_viz" / "cache" / "Hospital_General_Information.csv"
CMS_HGI_URL = "https://data.cms.gov/provider-data/dataset/xubh-q36u"
GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

# HHS poverty guidelines, 48 contiguous states + DC (used for the dollar axis on the page)
FPG = {"2026": {"base": 15960, "step": 5680, "url": "https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines"},
       "2025": {"base": 15650, "step": 5500, "url": "https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines/prior-hhs-poverty-guidelines-federal-register-references"}}

STATES = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
          "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
          "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
          "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
          "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
ABBR2FIPS = {v: k for k, v in STATES.items()}

# ---------------------------------------------------------------------------------------------
# State free-care floors in force as of November 2026. "applied" = a statewide minimum income
# line below which a hospital must give free (100%) care; discount-only or price-cap laws are
# recorded but not applied to the free-care line.
FLOORS = [
    dict(state="NY", floor=200, applied=1, scope="All general hospitals; waive all charges below 200% FPL",
         effective="2024-10-20", law="N.Y. Public Health Law 2807-k(9-a), as amended 2024",
         source="https://healthweb-back.health.ny.gov/facilities/hospital/financial_assist/docs/dal_24-01.pdf"),
    dict(state="WA", floor=300, applied=1, scope="Tier 1 hospitals (systems with 3+ acute hospitals in WA, and large hospitals): free to 300% FPL; all others (Tier 2): free to 200%",
         effective="2022-07-01", law="RCW 70.170.060(5) (2022 c 197); WA DOH hospital tier list DOH 346-149 (Nov 2025)",
         source="https://app.leg.wa.gov/RCW/default.aspx?cite=70.170.060"),
    dict(state="IL", floor=200, applied=1, scope="Uninsured Illinois residents; 200% FPL at urban hospitals, 125% at rural (outside a metro area) and critical access hospitals",
         effective="2012-06-14", law="Hospital Uninsured Patient Discount Act, 210 ILCS 89/10(a)(2),(4) (P.A. 97-690)",
         source="https://ilga.gov/legislation/ilcs/documents/021000890K10.htm"),
    dict(state="OR", floor=200, applied=1, scope="Nonprofit hospitals; household income up to 200% FPL adjusted by 100%",
         effective="2020-01-01", law="ORS 442.614(1)(a)(A) (Or. Laws 2019 c. 497, HB 3076)",
         source="https://oregon.public.law/statutes/ors_442.614"),
    dict(state="MD", floor=200, applied=1, scope="All acute and chronic care hospitals; free medically necessary care at or below 200% FPL",
         effective="before 2023", law="Md. Code, Health-General 19-214.1(b)(2)(i); COMAR 10.37.10.26",
         source="https://mgaleg.maryland.gov/2026RS/Statute_Web/ghg/19-214.1.pdf"),
    dict(state="NJ", floor=200, applied=1, scope="All acute care hospitals (NJ Charity Care); free at or below 200% of HHS poverty guidelines",
         effective="before 2023", law="N.J.A.C. 10:52-11.8(b)(1)",
         source="https://www.law.cornell.edu/regulations/new-jersey/N-J-A-C-10-52-11-8"),
    dict(state="RI", floor=200, applied=1, scope="Uninsured Rhode Island residents; full charity care up to and including 200% FPL",
         effective="before 2023", law="216-RICR-40-10-23.14",
         source="https://rules.sos.ri.gov/regulations/part/216-40-10-23"),
    dict(state="ME", floor=200, applied=1, scope="Maine residents; free medically necessary care at or below 200% FPL (150% before July 2026)",
         effective="2026-07-01", law="22 M.R.S. 1716-A(2) (P.L. 2025, c. 488)",
         source="https://legislature.maine.gov/legis/statutes/22/title22sec1716-A.html"),
    dict(state="MA", floor=150, applied=1, scope="Uninsured Massachusetts residents; Health Safety Net pays acute hospitals for care with no deductible at or below 150% FPL",
         effective="before 2023", law="101 CMR 613.04 (Health Safety Net)",
         source="https://www.law.cornell.edu/regulations/massachusetts/101-CMR-613-04"),
    dict(state="OH", floor=100, applied=1, scope="Ohio residents not on Medicaid; basic, medically necessary hospital services free at or below 100% FPL (HCAP)",
         effective="before 2023", law="Ohio Adm. Code 5160-2-17",
         source="https://codes.ohio.gov/ohio-administrative-code/rule-5160-2-17"),
    dict(state="CA", floor=None, applied=0, scope="Discount or charity care required up to 400% FPL for uninsured and high-cost patients; the law sets no free-care line",
         effective="2022-01-01", law="Cal. Health & Safety Code 127405 (AB 1020)",
         source="https://california.public.law/codes/health_and_safety_code_section_127405"),
    dict(state="CO", floor=None, applied=0, scope="Hospital Discounted Care: capped charges and payment limits at or below 250% FPL; not free care",
         effective="2022-09-01", law="HB21-1198",
         source="https://hcpf.colorado.gov/hospital-discounted-care"),
    dict(state="CT", floor=None, applied=0, scope="Uninsured patients at or below 250% FPL may be charged no more than cost; a price cap, not free care",
         effective="before 2023", law="Conn. Gen. Stat. 19a-673",
         source="https://law.justia.com/codes/connecticut/title-19a/chapter-368z/section-19a-673-formerly-sec-19a-169e/"),
    dict(state="NV", floor=None, applied=0, scope="Hospitals with 100+ beds must discount uninsured inpatient charges at least 30%, and give a set amount of indigent care each year; no per-patient free-care line",
         effective="before 2023", law="NRS 439B.260, 439B.320",
         source="https://www.leg.state.nv.us/nrs/nrs-439b.html"),
]
# Washington tiers, from WA DOH "Washington Charity Care Hospital Tiers, 2025" (DOH 346-149, Nov 2025):
# https://doh.wa.gov/sites/default/files/2022-10/HospitalTierListing.pdf
# Tier 1 (free to 300% FPL): each Schedule H facility name below -> the DOH list entry it is. Every other
# Washington facility on this page appears in the DOH Tier 2 column (free to 200%); the build logs any
# Washington facility found in neither list.
WA_DOH_URL = "https://doh.wa.gov/sites/default/files/2022-10/HospitalTierListing.pdf"
WA_TIER1 = {
    "KADLEC REGIONAL MEDICAL CENTER": "Providence/Kadlec Medical Center (license 161)",
    "LEGACY SALMON CREEK HOSPITAL": "Legacy/Salmon Creek Hospital (208)",
    "MULTICARE ALLENMORE HOSPITAL (ALLENMORE)": "MultiCare/Tacoma General - Allenmore (176)",
    "MULTICARE TACOMA GENERAL HOSPITAL (TG)": "MultiCare/Tacoma General - Allenmore (176)",
    "MULTICARE AUBURN MEDICAL CENTER (AUB)": "MultiCare/Auburn Regional Medical Center (183)",
    "MULTICARE CAPITAL MEDICAL CENTER (CAPMED)": "MultiCare/Capital Medical Center (197)",
    "MULTICARE COVINGTON HOSPITAL (COV)": "MultiCare/Covington Medical Center (212)",
    "MULTICARE DEACONESS HOSPITAL (DEAC)": "MultiCare/Deaconess Hospital (37)",
    "MULTICARE GOOD SAMARITAN HOSPITAL (GSH)": "MultiCare/Good Samaritan Hospital (81)",
    "MULTICARE VALLEY HOSPITAL (VALLEY)": "MultiCare/Valley Hospital (180)",
    "YAKIMA VALLEY MEMORIAL HOSPITAL ASSOCIATION": "MultiCare/Yakima Memorial Hospital (58)",
    "OVERLAKE MEDICAL CENTER & CLINICS": "Overlake Hospital Medical Center (131)",
    "PH SOUTHWEST MEDICAL CENTER": "PeaceHealth/Southwest Medical Center (170)",
    "PH ST JOHN MEDICAL CENTER": "PeaceHealth/Saint John Medical Center (26)",
    "PH ST JOSEPH MEDICAL CENTER": "PeaceHealth/Saint Joseph Hospital (145)",
    "PH UNITED GENERAL MEDICAL CENTER": "PeaceHealth/United General Hospital (206)",
    "PH PEACE ISLAND MEDICAL CENTER": "PeaceHealth/Peace Island Medical Center (211)",
    "PROVIDENCE CENTRALIA HOSPITAL": "Providence/Centralia Hospital (191)",
    "PROVIDENCE HOLY FAMILY HOSPITAL": "Providence/Holy Family Hospital (139)",
    "PROVIDENCE MT CARMEL HOSPITAL": "Providence/Mount Carmel Hospital (193)",
    "PROVIDENCE REGIONAL MED CTRCOLBY": "Providence/Regional Medical Center Everett (84)",
    "PROVIDENCE REGIONAL MED CTRPACIFIC": "Providence/Regional Medical Center Everett (84)",
    "PROVIDENCE SACRED HEART MEDICAL CENTER": "Providence/Sacred Heart Medical Center (162)",
    "PROVIDENCE ST JOSEPH'S HOSPITAL": "Providence/Saint Joseph's Hospital (194)",
    "PROVIDENCE ST MARY MEDICAL CENTER": "Providence/Saint Mary Medical Center (50)",
    "PROVIDENCE ST PETER HOSPITAL": "Providence/Saint Peter Hospital (159)",
    "SWEDISH CHERRY HILL": "Providence/Swedish - Cherry Hill (3)",
    "SWEDISH EDMONDS": "Providence/Swedish - Edmonds (138)",
    "SWEDISH FIRST HILL": "Providence/Swedish - First Hill (1)",
    "SWEDISH ISSAQUAH": "Providence/Swedish - Issaquah (210)",
    "ST ANNE HOSPITAL": "VMFH/Saint Anne Hospital (126)",
    "ST ANTHONY HOSPITAL": "VMFH/Saint Anthony Hospital (209)",
    "ST CLARE HOSPITAL": "VMFH/Saint Clare Hospital (132)",
    "ST ELIZABETH HOSPITAL": "VMFH/Saint Elizabeth Hospital (35)",
    "ST FRANCIS HOSPITAL": "VMFH/Saint Francis Community Hospital (201)",
    "ST JOSEPH MEDICAL CENTER": "VMFH/Saint Joseph Medical Center - Tacoma (32)",
    "HARRISON MEDICAL CENTER": "VMFH/Saint Michael Hospital (142); Harrison Medical Center is St. Michael Medical Center's former name",
    "VIRGINIA MASON MEDICAL CENTER": "VMFH/Virginia Mason Medical Center (10)",
    "EVERGREENHEALTH MEDICAL CENTER": "EvergreenHealth Kirkland (164)",
}
WA_TIER2 = {"ASTRIA TOPPENISH HOSPITAL", "SUNNYSIDE COMMUNITY HOSPITAL", "CONFLUENCE HEALTH HOSPITAL - CENTRAL", "CONFLUENCE HEALTH HOSPITAL - MARES",
            "GRAYS HARBOR COMMUNITY HOSPITAL", "TRI-STATE MEMORIAL HOSPITAL",
            "KAISER PERMANENTE CENTRAL HOSPITAL"}

# States that had not expanded Medicaid as of November 2026 (KFF, Status of State Medicaid Expansion Decisions)
NON_EXPANSION = {"AL", "FL", "GA", "KS", "MS", "SC", "TN", "TX", "WI", "WY"}
KFF_EXPANSION = "https://www.kff.org/medicaid/issue-brief/status-of-state-medicaid-expansion-decisions/"
SHOWCASE = ["06037", "13121", "17031", "36047", "48201", "04013"]  # Los Angeles CA, Fulton GA, Cook IL, Kings (Brooklyn) NY, Harris TX, Maricopa AZ

# Specialty hospitals that are not general emergency doors for adults (filers often tick
# "general medical & surgical" anyway)
CHILDRENS = re.compile(r"CHILDREN|PEDIATRIC|SHRINERS", re.I)
COMBINED = re.compile(r"\bINCL|\bAND\b.*CHILDREN|&.*CHILDREN|\bWITH\b.*CHILDREN", re.I)  # "Christ Hosp incl Hope Children's Hosp"
SPECIALTY = re.compile(r"REHAB|PSYCH|BEHAVIORAL|MENTAL|CANCER|ONCOLOG|CITY OF HOPE|"
                       r"ORTHOP|SPINE|HEART HOSPITAL|HEART INSTITUTE|CARDIAC HOSPITAL|EYE |EAR |LONG[- ]TERM|LTAC|SPECIALTY HOSP|"
                       r"SURGICAL HOSPITAL|SURGERY CENTER|SURGICAL CENTER|HOSPICE|SKILLED|NURSING|KINDRED|SELECT SPECIALTY|TRANSITIONAL CARE|"
                       r"CONTINUING CARE|RECOVERY|ADDICTION|SUBSTANCE|WOMEN'?S HOSPITAL|WOMAN'?S HOSPITAL|BIRTH CENTER|INFANTS|NATIONAL JEWISH|"
                       r"SPECIALTY CENTER|OUTPATIENT CENTER|BAYRIDGE", re.I)
# Names that are clinics or outpatient units, never trusted to inherit a hospital's CMS emergency flag
NOT_A_HOSPITAL = re.compile(r"PRIMARY CARE|CLINIC\b|CLINICS?$|PHYSICIAN|SURGERY|IMAGING|INFUSION|CATH LAB|URGENT CARE|LLC$", re.I)

# Facilities still listed on a filer's latest return but closed to emergency patients since then.
# Each entry: (state, name pattern, closure note with source).
KNOWN_CLOSED = [
    ("GA", r"ATLANTA MEDICAL CENTER", "Wellstar Atlanta Medical Center closed Nov 1, 2022; AMC South closed its ER and inpatient units in 2020 (Georgia Public Broadcasting, Aug 31 2022)"),
]
# Facilities whose latest Schedule H is old and has been superseded: closed, sold, or the same campus now
# reported on another filer's newer return. (state, name pattern, note with source)
SUPERSEDED = [
    ("IL", r"SPRING VALLEY", "St. Margaret's Health-Spring Valley closed June 16, 2023 (latest return TY2022; WCBU, June 12 2023: https://www.wcbu.org/local-news/2023-06-12/st-margarets-ceo-blames-their-bank-for-accelerating-decision-to-close-spring-valley-hospital)"),
    ("WA", r"^WENATCHEE VALLEY HOSPITAL", "Same campus (820 N Chelan Ave) as Confluence Health Hospital - Mares, which Central Washington Health Services Association reports on its TY2024 return"),
    ("LA", r"^TULANE", "Tulane Medical Center, Lakeview and Lakeside were sold by HCA to LCMC Health on Jan 3, 2023; the TY2022 Tulane return predates the sale (Fierce Healthcare: https://fiercehealthcare.com/providers/hca-healthcare-selling-3-tulane-university-hospitals-lcmc-health)"),
]
# For-profit-operated hospitals reported on a nonprofit partner's Schedule H. Not "nonprofit ERs" in the sense of this page.
JV_FILERS = {
    "741287016": "Methodist Healthcare Ministries of South Texas reports the hospitals of Methodist Healthcare System, a partnership majority-owned and operated by HCA Healthcare",
}
# Health systems that hold one hospital license for several campuses list one facility, at the main campus, on
# Schedule H. Campuses with their own emergency department are added here with the license's free-care line.
# (parent EIN, campus name, street, city, state, ZIP, county FIPS, source)
CAMPUSES = [
    ("133971298", "NYU LANGONE HOSPITAL - BROOKLYN", "150 55TH STREET", "BROOKLYN", "NY", "11220", "36047",
     "https://nyulangone.org/locations/emergency-department-at-nyu-langone-hospital-brooklyn"),
    ("133971298", "NYU LANGONE HOSPITAL - LONG ISLAND", "259 FIRST STREET", "MINEOLA", "NY", "11501", "36059",
     "https://nyulangone.org/locations/nyu-langone-hospital-long-island"),
    ("133957095", "NEWYORK-PRESBYTERIAN BROOKLYN METHODIST HOSPITAL", "506 SIXTH STREET", "BROOKLYN", "NY", "11215", "36047",
     "https://www.nyp.org/brooklyn"),
    ("133957095", "NEWYORK-PRESBYTERIAN/COLUMBIA UNIVERSITY IRVING MEDICAL CENTER", "622 WEST 168TH STREET", "NEW YORK", "NY", "10032", "36061",
     "https://www.nyp.org/locations/newyork-presbyterian-columbia-university-irving-medical-center"),
    ("133957095", "NEWYORK-PRESBYTERIAN ALLEN HOSPITAL", "5141 BROADWAY", "NEW YORK", "NY", "10034", "36061",
     "https://www.nyp.org/allen"),
    ("133957095", "NEWYORK-PRESBYTERIAN LOWER MANHATTAN HOSPITAL", "170 WILLIAM STREET", "NEW YORK", "NY", "10038", "36061",
     "https://www.nyp.org/lowermanhattan"),
    ("131624096", "MOUNT SINAI QUEENS", "25-10 30TH AVENUE", "ASTORIA", "NY", "11102", "36081",
     "https://www.mountsinai.org/locations/queens"),
    ("111631746", "INTERFAITH MEDICAL CENTER", "1545 ATLANTIC AVENUE", "BROOKLYN", "NY", "11213", "36047",
     "https://profiles.health.ny.gov/hospital/opcert/7001002H"),
]
# Spot checks of posted financial assistance policies for the 100% doors that drive the most people
# between doors (November 2026). "fap" = free-care line in the posted policy when it differs from Schedule H
# (then used in place of the reported line); otherwise None, and the reported line stands.
FAP_CHECKS = {
    ("CA", "PIH HEALTH DOWNEY HOSPITAL"): (None, "Posted policy E-85300-600 (Downey and Whittier, last revised 3/29/2022; Internet Archive copy of Jan 2026): free at or below 100% FPL, flat discounted charges from 101% to 400%",
                                          "https://web.archive.org/web/20260124091116/https://www.pihhealth.org/app/files/public/3202f33d-e122-4bd3-a4b2-796c395d7dbc/PHDH%20PHWH%20Financial%20Assistance%20Policy%20-FAP-%20AKA%20Charity%20Care-Uncompensated%20Care%20Program%20-E-85300-600.pdf"),
    ("CA", "PIH HEALTH WHITTIER HOSPITAL"): (None, "Same policy as PIH Health Downey: free at or below 100% FPL",
                                             "https://web.archive.org/web/20260124091116/https://www.pihhealth.org/app/files/public/3202f33d-e122-4bd3-a4b2-796c395d7dbc/PHDH%20PHWH%20Financial%20Assistance%20Policy%20-FAP-%20AKA%20Charity%20Care-Uncompensated%20Care%20Program%20-E-85300-600.pdf"),
    ("CA", "EISENHOWER MEDICAL CENTER"): (None, "Patient Financial Assistance Policy (updated 2/7/2025): charity care (100% waiver) at or below 100% FPL; discounts to 400%",
                                          "https://eisenhowerhealth.org/resources/billing/help-paying-your-bill/patient-financial-assistance-policy"),
    ("PA", "TEMPLE UNIVERSITY HOSPITAL INC"): (None, "TUH 2024 charity care table: free below 100% FPL; 75%, 50%, 25% discounts to 400%",
                                               "https://templehealth.org/sites/default/files/2025-01/tuh-2024-federal-poverty-level-for-charity-care-financial-assistance.pdf"),
    ("NV", "BOULDER CITY HOSPITAL INC"): (200, "Posted plain-language policy (May 2024): free care at or below 200% FPL, sliding discounts to 300%; its Schedule H reports 100%",
                                          "https://bchcares.org/wp-content/uploads/2024/05/FINANCIAL-ASSISTANCE-POLICY-PLAIN-LANGUAGE.pdf"),
}
# General hospitals with an ER whose Schedule H leaves the 24-hour ER box blank and that CMS's file cannot
# confirm by ZIP (CMS lists them at another address). EIN -> source.
ER_CONFIRMED = {
    "111631746": "Brookdale Hospital Medical Center: CMS CCN 330233 lists emergency services (CMS gives ZIP 11212, Schedule H 11236); Level I trauma center",
}

log_lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log_lines.append(s)


def curl(url, dest):
    return irs_scan.curl(url, dest)


def norm(s):
    s = (s or "").upper().replace("&AMP;", "&")
    s = re.sub(r"\bSAINT\b", "ST", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


STOP = set("THE INC LLC CORP CORPORATION OF AND AT HOSPITAL HOSPITALS MEDICAL CENTER CENTRE CTR MED HEALTH HEALTHCARE SYSTEM SYSTEMS "
           "REGIONAL REG COMMUNITY CAMPUS MEMORIAL CARE SERVICES".split())


def tokens(s):
    return {t for t in norm(s).split() if t not in STOP and len(t) > 1}


def jaccard(a, b):
    a, b = tokens(a), tokens(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def pct(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if 50 <= v <= 1000 else None   # 0, blanks and typos (12, 10000) are not usable lines


# ---------------------------------------------------------------------------------------------
# 1-2. Latest return per filer, and Section B -> facility linking

def latest_returns(rows):
    best = {}
    for r in rows:
        key = (r["period_end"] or "", r["oid"])
        if r["ein"] not in best or key > best[r["ein"]][0]:
            best[r["ein"]] = (key, r)
    return [v[1] for v in best.values()]


GROUP_RX = [re.compile(r"\bGROUP\s+([A-Z0-9]{1,2})\b"), re.compile(r"^([A-Z0-9]{1,2})\s*[-:.)]"), re.compile(r"^([A-Z0-9]{1,2})$"),
            re.compile(r"^([A-Z0-9]{1,2})\s+(?:FACILIT|HOSPITAL|-)"), re.compile(r"^([A-Z])\s+\d+\s+FACILIT")]


def link_return(r):
    """Return [(facility, policy, method)] for one return; unlinked facilities get policy None."""
    facs, pols = r["fac"], r["pol"]
    if not facs:
        return []
    if not pols:
        return [(f, None, "no Section B") for f in facs]
    lines = {pct(p["FPGFamilyIncmLmtFreeCarePct"]) for p in pols}
    if len(pols) == 1:
        return [(f, pols[0], "single policy") for f in facs]
    codes = {(f["FacilityReportingGroupCd"] or "").strip().upper() for f in facs} - {""}
    assign = {}  # facility index -> (policy, method)
    claimed_codes = set()
    # a) policy names that are a reporting-group code ("A", "Group B", "C-8 Facilities ...")
    for p in pols:
        n = norm(p["name"])
        code = None
        for rx in GROUP_RX:
            m = rx.search(n)
            if m and m.group(1) in codes:
                code = m.group(1)
                break
        if code and not any(jaccard(p["name"], f["name"]) >= 0.5 for f in facs):
            claimed_codes.add(code)
            for i, f in enumerate(facs):
                if (f["FacilityReportingGroupCd"] or "").strip().upper() == code:
                    assign[i] = (p, "group code")
    # b) policy names that name a facility
    for p in pols:
        scores = [(jaccard(p["name"], f["name"]) if norm(p["name"]) != norm(f["name"]) else 1.0, i) for i, f in enumerate(facs)]
        s, i = max(scores)
        if s >= 0.5 and i not in assign:
            assign[i] = (p, "facility name")
            code = (facs[i]["FacilityReportingGroupCd"] or "").strip().upper()
            if code and code not in claimed_codes:   # a group named after its first facility
                claimed_codes.add(code)
                for j, f in enumerate(facs):
                    if j not in assign and (f["FacilityReportingGroupCd"] or "").strip().upper() == code:
                        assign[j] = (p, "group of named facility")
    # c) line numbers, when every policy points at a different facility number
    nums = [tuple(p["nums"]) for p in pols]
    if len(set(nums)) == len(nums) and all(nums):
        byn = {f["FacilityNum"]: i for i, f in enumerate(facs)}
        for p in pols:
            for n in p["nums"]:
                i = byn.get(n)
                if i is not None and i not in assign:
                    assign[i] = (p, "facility number")
    # d) every policy block reports the same free-care line: linking can't change the line
    if len(lines) == 1:
        for i, f in enumerate(facs):
            if i not in assign:
                assign[i] = (pols[0], "all policies identical")
    # e) as many policies as reporting groups, in order
    sorted_codes = sorted(codes, key=lambda c: (len(c), c))
    if len(pols) == len(sorted_codes) and not claimed_codes:
        for p, code in zip(pols, sorted_codes):
            for i, f in enumerate(facs):
                if i not in assign and (f["FacilityReportingGroupCd"] or "").strip().upper() == code:
                    assign[i] = (p, "group order")
    return [(f, *assign.get(i, (None, "unlinked"))) for i, f in enumerate(facs)]


# ---------------------------------------------------------------------------------------------
# 3. CMS Hospital General Information match

def load_hgi():
    rows = list(csv.DictReader(open(CMS_HGI, encoding="utf-8-sig")))
    byzip = defaultdict(list)
    for h in rows:
        byzip[h["ZIP Code"][:5].zfill(5)].append(h)
    return rows, byzip


def match_hgi(f, byzip):
    z = (f["zip"] or "")[:5]
    cands = byzip.get(z, [])
    num = re.match(r"\s*(\d+)", f["addr"] or "")
    best, bs = None, 0.0
    for h in cands:
        s = jaccard(f["name"], h["Facility Name"])
        hn = re.match(r"\s*(\d+)", h["Address"] or "")
        if num and hn and num.group(1) == hn.group(1):
            s += 0.5
        if s > bs:
            best, bs = h, s
    if best and bs >= 0.5:   # names share half their distinctive words, or same street number and some name overlap
        return best
    return None


def strong_name(f, h):
    """Name match good enough to trust CMS's emergency-services flag over a blank Schedule H box."""
    return norm(f["name"]) == norm(h["Facility Name"]) or jaccard(f["name"], h["Facility Name"]) >= 0.5


# ---------------------------------------------------------------------------------------------
# 4. Geography

def geocode_counties(facs):
    """Census geocoder (current geographies) -> {id: 5-digit county}, cached."""
    path = CACHE / "geocode_counties.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    todo = [f for f in facs if f["id"] not in done]
    for i in range(0, len(todo), 1000):
        chunk = todo[i:i + 1000]
        buf = io.StringIO()
        w = csv.writer(buf)
        for f in chunk:
            w.writerow([f["id"], f["addr"] or "", f["city"] or "", f["state"] or "", (f["zip"] or "")[:5]])
        src = CACHE / "geo_in.csv"
        src.write_text(buf.getvalue())
        for attempt in range(4):
            p = subprocess.run(["curl", "-s", "-m", "900", "-A", UA, "--form", f"addressFile=@{src}", "--form", "benchmark=Public_AR_Current",
                                "--form", "vintage=Current_Current", GEOCODER], capture_output=True, text=True)
            if p.returncode == 0 and p.stdout.strip():
                break
            time.sleep(15)
        else:
            raise RuntimeError("Census geocoder failed")
        for row in csv.reader(io.StringIO(p.stdout)):
            if len(row) > 9 and row[2] == "Match" and row[8] and row[9]:
                done[row[0]] = row[8] + row[9]
            elif row:
                done.setdefault(row[0], None)
        path.write_text(json.dumps(done))
        log(f"  geocoded {min(i + 1000, len(todo))}/{len(todo)}")
    return done


def zcta_county():
    """ZCTA -> county with the largest share of the ZCTA's land area (2020 geography)."""
    path = curl(ZCTA_COUNTY, CACHE / "tab20_zcta520_county20_natl.txt")
    best = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="|"):
            z, c, a = r["GEOID_ZCTA5_20"], r["GEOID_COUNTY_20"], int(r["AREALAND_PART"] or 0)
            if z and (z not in best or a > best[z][1]):
                best[z] = (c, a)
    return {z: c for z, (c, a) in best.items()}


CT_ALIASES = {"WILLIMANTIC": "WINDHAM", "STAFFORD SPRINGS": "STAFFORD", "ROCKVILLE": "VERNON", "DANIELSON": "KILLINGLY",
              "WINSTED": "WINCHESTER", "STORRS": "MANSFIELD", "WATERFORD": "WATERFORD"}


def ct_regions():
    """Connecticut town -> planning region (the county-equivalents ACS uses since 2022)."""
    path = curl(CT_TOWNS, CACHE / "ct_cou_to_cousub_crosswalk.txt")
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().replace('"', "").replace("\n(INCITS", " (INCITS").splitlines()
    for line in lines:
        p = line.split("|")
        if len(p) > 8 and p[0] == "09" and p[3].isdigit():
            town = re.sub(r" (town|city|borough)$", "", p[8]).upper()
            out[town] = "09" + p[3]
    return out


def metro_counties():
    path = curl(RUCC, CACHE / "rucc2023.csv")
    out = {}
    with open(path, newline="", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            if r["Attribute"] == "RUCC_2023":
                out[r["FIPS"].zfill(5)] = int(r["Value"]) <= 3
    return out


# ---------------------------------------------------------------------------------------------
# 5. ACS

C_EDGES = [0, 100, 138, 200, 400, None]   # C27016 ratio-of-income-to-poverty bins (percent)
F_EDGES = [0, 50, 75, 100, 125, 150, 175, 185, 200, 300, 400, 500, None]  # B17024 bins (finer, all coverage)
TOP = 1000  # treat the open top bins as running to 10x poverty for interpolation


def read_acs(table, cols):
    path = curl(ACS_URL.format(t=table.lower()), CACHE / f"acsdt5y2024-{table.lower()}.dat")
    out = {}
    with open(path, encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("|")
        idx = [head.index(c) for c in cols]
        for line in f:
            if not line.startswith("0500000US"):
                continue
            p = line.rstrip("\n").split("|")
            out[p[0][9:]] = [float(p[i]) if p[i] not in ("", "null") else 0.0 for i in idx]
    return out


def acs_county_bins():
    """Uninsured under 65 by C27016 bin, and the B17024 fine-bin shape of everyone under 60."""
    # C27016: for each of 5 bins, under-19 no coverage and 19-64 no coverage; also totals with coverage
    starts = [2, 12, 22, 32, 42]
    cols = []
    for s in starts:
        cols += [f"C27016_E{s + 3:03d}", f"C27016_E{s + 6:03d}", f"C27016_E{s + 2:03d}", f"C27016_E{s + 5:03d}"]
    c = read_acs("C27016", cols)
    unins = {k: [v[4 * i] + v[4 * i + 1] for i in range(5)] for k, v in c.items()}
    pop_u65 = {k: sum(v[4 * i] + v[4 * i + 1] + v[4 * i + 2] + v[4 * i + 3] for i in range(5)) for k, v in c.items()}
    # B17024 age groups under 6, 6-11, 12-17, 18-59: lines 3-14, 16-27, 29-40, 42-53
    bcols = [f"B17024_E{a + j:03d}" for a in (3, 16, 29, 42) for j in range(12)]
    b = read_acs("B17024", bcols)
    shape = {k: [sum(v[g * 12 + j] for g in range(4)) for j in range(12)] for k, v in b.items()}
    return unins, pop_u65, shape


def count_between(lo, hi, bins, shape):
    """Uninsured people with income ratio in (lo, hi] percent of poverty.

    Returns (conservative, interpolated): conservative counts only C27016 bins that lie wholly
    inside (lo, hi]; interpolated splits partial bins in proportion to the county's B17024
    population in each finer sub-bin, linearly within sub-bins.
    """
    if hi <= lo:
        return 0.0, 0.0
    cons = interp = 0.0
    for i in range(5):
        a, bnd = C_EDGES[i], C_EDGES[i + 1] if C_EDGES[i + 1] is not None else TOP
        n = bins[i]
        if n <= 0:
            continue
        if a >= lo and bnd <= hi and C_EDGES[i + 1] is not None:
            cons += n
        ov_lo, ov_hi = max(a, lo), min(bnd, hi)
        if ov_hi <= ov_lo:
            continue
        # share of the bin's population inside the overlap, from the finer B17024 shape
        tot = part = 0.0
        for j in range(12):
            fa, fb = F_EDGES[j], F_EDGES[j + 1] if F_EDGES[j + 1] is not None else TOP
            sa, sb = max(fa, a), min(fb, bnd)
            if sb <= sa:
                continue
            w = shape[j] * (sb - sa) / (fb - fa)
            tot += w
            oa, ob = max(sa, ov_lo), min(sb, ov_hi)
            if ob > oa:
                part += shape[j] * (ob - oa) / (fb - fa)
        frac = part / tot if tot > 0 else (ov_hi - ov_lo) / (bnd - a)
        interp += n * frac
    return cons, interp


def count_at_or_below(line, bins, shape):
    return count_between(-1, line, bins, shape)


# ---------------------------------------------------------------------------------------------

def main():
    OUT.mkdir(exist_ok=True)
    rows = irs_scan.scan_all()
    log(f"Schedule H returns scanned: {len(rows)} from releases {irs_scan.RELEASES}; filers (EINs): {len({r['ein'] for r in rows})}")
    latest = latest_returns(rows)
    log(f"Latest return per filer: {len(latest)}; tax years {dict(sorted(Counter(r['taxyr'] for r in latest).items()))}")

    # Link policies to facilities
    facs, methods, unlinked = [], Counter(), []
    for r in latest:
        for f, p, how in link_return(r):
            methods[how] += 1
            if p is None:
                unlinked.append(f"{r['ein']} {r['filer']} | {f['name']} ({f['state']})")
                continue
            facs.append({
                "ein": r["ein"], "filer": r["filer"], "taxyr": r["taxyr"], "period_end": r["period_end"], "oid": r["oid"],
                "name": (f["name"] or "").replace("&amp;", "&"), "addr": f["addr"], "city": f["city"], "state": f["state"], "zip": (f["zip"] or "")[:5],
                "er": f["EmergencyRoom24HrsInd"] == "X", "general": f["GeneralMedicalAndSurgicalInd"] == "X",
                "childrens": f["ChildrensHospitalInd"] == "X", "cah": f["CriticalAccessHospitalInd"] == "X",
                "line": pct(p["FPGFamilyIncmLmtFreeCarePct"]), "line_raw": p["FPGFamilyIncmLmtFreeCarePct"],
                "disc": pct(p["FPGFamilyIncmLmtDscntCarePct"]),
                "asset": p["AssetLevelCriteriaInd"] == "X", "residency": p["ResidencyCriteriaInd"] == "X", "link": how,
            })
    log(f"Facility links: {dict(methods)}")
    log(f"Unlinked facilities: {len(unlinked)}")
    for u in unlinked:
        log("   unlinked:", u)

    # De-duplicate facilities listed by more than one filer (keep the latest return)
    best = {}
    for f in facs:
        k = (f["zip"], norm(f["name"]))
        if k not in best or (f["period_end"] or "", f["oid"]) > (best[k]["period_end"] or "", best[k]["oid"]):
            best[k] = f
    log(f"Facilities with a linked policy: {len(facs)}; after de-duplication: {len(best)}")
    facs = list(best.values())
    for i, f in enumerate(sorted(facs, key=lambda f: (f["ein"], f["name"]))):
        f["id"] = f"F{i:05d}"
    valid = [f for f in facs if f["line"] is not None]
    log(f"Facilities with a usable free-care line (50-1000% FPG): {len(valid)} of {len(facs)}; filers {len({f['ein'] for f in valid})}")

    # Context stats on every facility line (the beeswarm)
    lines_all = [f["line"] for f in valid]
    ctx = {
        "facilities": len(valid), "filers": len({f["ein"] for f in valid}),
        "median": statistics.median(lines_all),
        "pct_at_200": round(100 * sum(1 for v in lines_all if v == 200) / len(lines_all), 1),
        "pct_le_150": round(100 * sum(1 for v in lines_all if v <= 150) / len(lines_all), 1),
        "pct_ge_300": round(100 * sum(1 for v in lines_all if v >= 300) / len(lines_all), 1),
        "pct_asset_test": round(100 * sum(1 for f in valid if f["asset"]) / len(valid), 1),
        "pct_residency_test": round(100 * sum(1 for f in valid if f["residency"]) / len(valid), 1),
    }

    # Extra campuses of multi-campus licenses (added after the context stats, which describe Schedule H as filed)
    byein = defaultdict(list)
    for f in facs:
        byein[f["ein"]].append(f)
    campus_rows = []
    for i, (ein, name, addr, city, st, z, cty, src) in enumerate(CAMPUSES):
        parents = byein.get(ein)
        if not parents:
            log("   campus parent missing:", ein, name)
            continue
        c = dict(parents[0])
        c.update(id=f"C{i:03d}", parent_id=parents[0]["id"], name=name, addr=addr, city=city, state=st, zip=z, county_fixed=cty, campus=src,
                 er=True, general=True, childrens=False, cah=False)
        campus_rows.append(c)
    log(f"Campuses added for multi-campus licenses: {len(campus_rows)}")

    # General acute hospitals with a 24-hour ER (with or without a usable free-care line)
    hgi, byzip = load_hgi()
    pool = facs + campus_rows
    for f in pool:
        h = None if f.get("campus") else match_hgi(f, byzip)
        f["_h"] = h
        f["ccn"] = h["Facility ID"] if h else ""
        f["cms_type"] = h["Hospital Type"] if h else ""
        f["cms_er"] = h["Emergency Services"] if h else ""
        f["cms_county"] = h["County/Parish"] if h else ""
        if h:   # CMS's designation beats the Schedule H box (some large hospitals tick "critical access" by mistake)
            f["cah"] = h["Hospital Type"] == "Critical Access Hospitals"
        f.setdefault("campus", "")
    byid = {f["id"]: f for f in facs}
    for c in campus_rows:   # campuses share their license's CMS certification number
        c["ccn"] = byid[c["parent_id"]]["ccn"]
    ticked_ccns = {f["ccn"] for f in pool if f["er"] and f["ccn"]}
    rescue_ccns = set()
    keep, noline, drops, stale_dropped = [], [], Counter(), []
    for f in sorted(pool, key=lambda f: (-(f["line"] is not None), f["id"])):
        h = f["_h"]
        note = lambda lst: next((n for st, rx, n in lst if f["state"] == st and re.search(rx, f["name"], re.I)), None)
        closed, sup = note(KNOWN_CLOSED), note(SUPERSEDED)
        # Many large general hospitals tick the Schedule H "children's hospital" box because they house
        # one, and some leave "general medical & surgical" blank; CMS's hospital type settles it when
        # the facility matches CMS's list, the 990 boxes and the name decide otherwise.
        acute = h["Hospital Type"] in ("Acute Care Hospitals", "Critical Access Hospitals", "Rural Emergency Hospital") if h else None
        kids_name = bool(CHILDRENS.search(f["name"]) and not COMBINED.search(f["name"]))
        # A blank Schedule H ER box is overridden when CMS lists the same hospital (strong name match, one
        # facility per CCN, and no other facility on Schedule H already claims that CCN's ER) as an acute or
        # critical access hospital with emergency services.
        er_cms = bool(h and strong_name(f, h) and not NOT_A_HOSPITAL.search(f["name"]) and h["Emergency Services"] == "Yes"
                      and h["Hospital Type"] in ("Acute Care Hospitals", "Critical Access Hospitals")
                      and f["ccn"] not in ticked_ccns and f["ccn"] not in rescue_ccns)
        manual = f["ein"] in ER_CONFIRMED and not f.get("campus")
        if f.get("campus"):
            f["er_src"] = "campus"
        elif f["er"]:
            f["er_src"] = "Schedule H"
        elif manual:
            f["er_src"] = "confirmed"
        elif er_cms:
            f["er_src"] = "CMS"
        else:
            f["er_src"] = ""
        if f.get("campus"):
            why = None
        elif not f["er_src"]:
            why = "no 24-hour ER on Schedule H or in CMS's file"
        elif acute is False:
            why = f"CMS type {h['Hospital Type']}"
        elif acute is None and not f["general"] and not manual:
            why = "not general medical & surgical (no CMS match)"
        elif kids_name or SPECIALTY.search(f["name"]) or (acute is None and f["childrens"]):
            why = "children's or specialty hospital"
        elif closed:
            why = "closed since filing"
            log("   closed:", f["name"], "-", closed)
        elif sup:
            why = "superseded (closed, sold, or reported by a newer filer)"
            log("   superseded:", f["name"], f"TY{f['taxyr']}", "-", sup)
        elif int(f["taxyr"] or 0) <= 2022 and not h:
            why = "return from tax year 2022 or earlier and not in CMS's current list"
            stale_dropped.append(f)
        elif f["ein"] in JV_FILERS:
            why = "operated by a for-profit partnership"
        else:
            why = None
        if why:
            drops[why + ("" if f["line"] is not None else " [no line]")] += 1
            continue
        if f["er_src"] == "CMS":
            rescue_ccns.add(f["ccn"])
        (keep if f["line"] is not None else noline).append(f)
    for f in stale_dropped:
        log("   stale, dropped:", f["name"], f["state"], f"TY{f['taxyr']}", f"line {f['line']}")
    # The same campus listed by two filers under different names: keep the latest return
    seen = {}
    for f in sorted(keep + noline, key=lambda f: (f["period_end"] or "", f["oid"]), reverse=True):
        k = (f["zip"], re.sub(r"\s+", " ", norm(f["addr"])))
        if f.get("campus") or not f["addr"]:
            continue
        if k in seen and int(f["taxyr"]) < int(seen[k]["taxyr"]):   # same address, older return
            log("   same address as a newer filing, dropped:", f["name"], f"TY{f['taxyr']}", "| kept:", seen[k]["name"], f"TY{seen[k]['taxyr']}")
            f["_dup"] = True
            drops["same campus as a newer filing" + ("" if f["line"] is not None else " [no line]")] += 1
        elif k not in seen:
            seen[k] = f
    keep = [f for f in keep if not f.get("_dup")]
    noline = [f for f in noline if not f.get("_dup")]
    rescued = [f for f in keep + noline if f["er_src"] in ("CMS", "confirmed")]
    log(f"General acute ER facilities kept: {len(keep)} with a usable line, {len(noline)} without; dropped: {dict(drops)}")
    log(f"  ER box blank on Schedule H but ER confirmed by CMS or by hand: {len(rescued)} ({sum(1 for f in rescued if f['line'] is not None)} with a usable line)")
    for f in rescued:
        log("   ER from", f["er_src"] + ":", f["name"], f["state"], f"line {f['line']}", f["ccn"])
    log(f"  matched to CMS Hospital General Information: {sum(1 for f in keep if f['ccn'])}")

    # Counties
    geo = geocode_counties([f for f in keep + noline if not f["campus"]])
    zc = zcta_county()
    acs_names = {}
    path = curl(ACS_GEOS, CACHE / "Geos20245YR.txt")
    with open(path, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            if r["SUMLEVEL"] == "050":
                acs_names[r["GEO_ID"][9:]] = r["NAME"]
    by_name = {}
    for fips, nm in acs_names.items():
        by_name[(norm(nm.split(",")[0]), STATES.get(fips[:2]))] = fips
    ct = ct_regions()
    city_cty = defaultdict(set)   # (city, state) -> counties of CMS-listed hospitals there, for PO-box ZIPs
    for h in hgi:
        c = by_name.get((norm(h["County/Parish"] + " COUNTY"), h["State"])) or by_name.get((norm(h["County/Parish"] + " PARISH"), h["State"]))
        if c:
            city_cty[(norm(h["City/Town"]), h["State"])].add(c)
    nmeth = Counter()
    for f in keep + noline:
        c = geo.get(f["id"])
        cms = f["cms_county"] and (by_name.get((norm(f["cms_county"] + " COUNTY"), f["state"])) or by_name.get((norm(f["cms_county"] + " PARISH"), f["state"]))
                                   or by_name.get((norm(f["cms_county"]), f["state"])))
        if f["campus"]:
            f["county"], how = f["county_fixed"], "campus list"
        elif f["state"] == "CT":   # ACS uses planning regions; place by town
            town = norm(f["city"])
            f["county"], how = ct.get(CT_ALIASES.get(town, town)), "CT town"
        elif c and c in acs_names:
            f["county"], how = c, "address"
        elif zc.get(f["zip"]) in acs_names:
            f["county"], how = zc[f["zip"]], "ZIP"
        elif cms:
            f["county"], how = cms, "CMS county"
        elif len(city_cty.get((norm(f["city"]), f["state"]), ())) == 1:
            f["county"], how = next(iter(city_cty[(norm(f["city"]), f["state"])])), "city"
        else:
            f["county"], how = None, "none"
        if f["county"] is None:
            how = "none"
        if f["line"] is not None:
            nmeth[how] += 1
    log(f"County placement: {dict(nmeth)}")
    for f in keep + noline:
        if f["county"] is None:
            log("   no county:", f["name"], f["city"], f["state"], f["zip"])
    keep = [f for f in keep if f["county"]]
    noline = [f for f in noline if f["county"]]

    # State floors
    metro = metro_counties()
    floors = {d["state"]: d for d in FLOORS if d["applied"]}
    for f in keep:
        st = f["state"]
        fl = None
        if st == "WA":
            nm = f["name"].upper().strip()
            fl = 300 if nm in WA_TIER1 else 200
            if nm not in WA_TIER1 and nm not in WA_TIER2:
                log("   WA facility not matched to the DOH tier list, Tier 2 assumed:", f["name"], f["city"])
        elif st == "IL":
            rural = f["cah"] or not metro.get(f["county"], True)
            fl = 125 if rural else 200
        elif st in floors:
            fl = floors[st]["floor"]
        chk = FAP_CHECKS.get((st, f["name"].upper().strip()))
        f["fap"] = chk[0] if chk and chk[0] else ""
        f["fap_note"] = chk[1] if chk else ""
        f["fap_src"] = chk[2] if chk else ""
        base = f["fap"] or f["line"]
        f["base"] = base   # the hospital's own line: Schedule H, or its posted policy where a spot check found a difference
        f["floor"] = fl
        f["eff"] = max(base, fl) if fl else base
        f["floor_binds"] = bool(fl and fl > base)
    found = {(f["state"], f["name"].upper().strip()) for f in keep}
    for k, v in FAP_CHECKS.items():
        log("   FAP check", "MISSING" if k not in found else "", k, "->", v[0] or "reported line confirmed")
    log(f"State floor raises the line at {sum(f['floor_binds'] for f in keep)} of {len(keep)} general ER facilities: "
        f"{dict(Counter(f['state'] for f in keep if f['floor_binds']))}")

    # ACS join
    unins, pop_u65, shape = acs_county_bins()
    byc = defaultdict(list)
    for f in keep:
        byc[f["county"]].append(f)
    nolc = defaultdict(list)
    for f in noline:
        nolc[f["county"]].append(f)

    def county_stats(fs, key, cms_only=False):
        fs = [f for f in fs if f["ccn"]] if cms_only else fs
        if len(fs) < 1:
            return None
        lo, hi = min(f[key] for f in fs), max(f[key] for f in fs)
        return lo, hi

    out_c = []
    tot = defaultdict(float)
    for c, fs in byc.items():
        bins, sh = unins.get(c), shape.get(c)
        if bins is None or sh is None:
            log("   no ACS for county", c)
            continue
        u = sum(bins)
        nl = sorted(nolc.get(c, []), key=lambda f: f["name"])
        rec = {"fips": c, "name": acs_names[c], "state": STATES.get(c[:2], ""), "doors": len(fs), "uninsured_u65": round(u),
               "b0_100": round(bins[0]), "b100_138": round(bins[1]), "b138_200": round(bins[2]), "b200_400": round(bins[3]), "b400_up": round(bins[4]),
               "doors_noline": len(nl), "noline_names": "; ".join(f["name"] for f in nl)}
        for key, tag in (("eff", ""), ("base", "_raw")):
            lo, hi = county_stats(fs, key)
            cons, interp = count_between(lo, hi, bins, sh)
            elig_lo = count_at_or_below(lo, bins, sh)[1]
            elig_hi = count_at_or_below(hi, bins, sh)[1]
            rec.update({f"min{tag}": lo, f"max{tag}": hi, f"gap_cons{tag}": round(cons), f"gap_interp{tag}": round(interp),
                        f"elig_min{tag}": round(elig_lo), f"elig_max{tag}": round(elig_hi)})
            differs = hi > lo
            tot[f"counties_differ{tag}"] += differs
            tot[f"unins_in_differ{tag}"] += u if differs else 0
            tot[f"gap_cons{tag}"] += cons
            tot[f"gap_interp{tag}"] += interp
            if differs:
                tot[f"elig_min_sum{tag}"] += elig_lo
                tot[f"elig_max_sum{tag}"] += elig_hi
        # sensitivity: leave out people under 138% of poverty in Medicaid expansion states
        lo, hi = rec["min"], rec["max"]
        lo_x = lo if rec["state"] in NON_EXPANSION else max(lo, 138)
        cons, interp = count_between(lo_x, hi, bins, sh)
        rec["gap_cons_xmcd"], rec["gap_interp_xmcd"] = round(cons), round(interp)
        tot["gap_cons_xmcd"] += cons
        tot["gap_interp_xmcd"] += interp
        if c != "06037":
            tot["gap_cons_xla"] += rec["gap_cons"]
            tot["gap_interp_xla"] += rec["gap_interp"]
        if hi > lo:   # old returns that set a county's lowest or highest line
            for f in fs:
                if int(f["taxyr"]) <= 2023 and f["eff"] in (lo, hi):
                    tot["stale_extremes"] += 1
                    log(f"   TY{f['taxyr']} return sets the {'min' if f['eff'] == lo else 'max'} in {acs_names[c]} ({lo}-{hi}):", f["name"], f"line {f['line']}", f"CCN {f['ccn'] or '-'}")
        # sensitivity: only doors matched to CMS's hospital list
        cm = county_stats(fs, "eff", cms_only=True)
        if cm:
            cons, interp = count_between(cm[0], cm[1], bins, sh)
            tot["gap_cons_cms"] += cons
            tot["gap_interp_cms"] += interp
            tot["counties_differ_cms"] += cm[1] > cm[0]
        tot["counties_with_door"] += 1
        tot["unins_with_door"] += u
        out_c.append(rec)
    us_unins = sum(sum(v) for k, v in unins.items() if k[:2] in STATES)

    # Write outputs ---------------------------------------------------------------------------
    fcols = ["id", "name", "filer", "ein", "taxyr", "city", "state", "zip", "county", "line", "floor", "eff", "floor_binds", "disc",
             "asset", "residency", "cah", "ccn", "link", "er_src", "campus", "fap", "fap_note", "fap_src"]
    with open(OUT / "facilities.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fcols, extrasaction="ignore")
        w.writeheader()
        for f in sorted(keep, key=lambda f: (f["county"], f["eff"], f["name"])):
            w.writerow({**f, "floor": f["floor"] or "", "floor_binds": int(f["floor_binds"]), "asset": int(f["asset"]),
                        "residency": int(f["residency"]), "cah": int(f["cah"]), "disc": f["disc"] or "",
                        "line": f"{f['line']:g}", "eff": f"{f['eff']:g}"})
    ccols = ["fips", "name", "state", "doors", "uninsured_u65", "b0_100", "b100_138", "b138_200", "b200_400", "b400_up",
             "min", "max", "gap_cons", "gap_interp", "elig_min", "elig_max", "min_raw", "max_raw", "gap_cons_raw", "gap_interp_raw",
             "gap_cons_xmcd", "gap_interp_xmcd", "doors_noline", "noline_names"]
    with open(OUT / "counties.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ccols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(out_c, key=lambda r: r["fips"]):
            w.writerow({k: (f"{v:g}" if isinstance(v, float) else v) for k, v in r.items()})
    with open(OUT / "floors.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["state", "floor", "applied", "scope", "effective", "law", "source"])
        w.writeheader()
        for d in FLOORS:
            w.writerow({**d, "floor": d["floor"] or ""})
    def m(x):
        return round(x / 1e6, 2)
    differ = [r for r in out_c if r["max"] > r["min"]]
    summary = {
        "built": time.strftime("%Y-%m-%d"),
        "fpg": FPG,
        "context_all_facilities": ctx,
        "general_er_facilities": len(keep), "general_er_filers": len({f["ein"] for f in keep}),
        "general_er_median_line": statistics.median(f["eff"] for f in keep),
        "general_er_taxyrs": dict(sorted(Counter(f["taxyr"] for f in keep).items())),
        "floor_binds": sum(f["floor_binds"] for f in keep),
        "floor_binds_by_state": dict(Counter(f["state"] for f in keep if f["floor_binds"])),
        "counties_with_door": int(tot["counties_with_door"]),
        "counties_multi_door": sum(1 for r in out_c if r["doors"] > 1),
        "counties_differ": int(tot["counties_differ"]), "counties_differ_raw": int(tot["counties_differ_raw"]),
        "unins_in_differ_m": m(tot["unins_in_differ"]), "unins_in_differ_raw_m": m(tot["unins_in_differ_raw"]),
        "gap_cons_m": m(tot["gap_cons"]), "gap_interp_m": m(tot["gap_interp"]),
        "gap_cons_raw_m": m(tot["gap_cons_raw"]), "gap_interp_raw_m": m(tot["gap_interp_raw"]),
        "gap_cons_xmcd_m": m(tot["gap_cons_xmcd"]), "gap_interp_xmcd_m": m(tot["gap_interp_xmcd"]),
        "gap_cons_xla_m": m(tot["gap_cons_xla"]), "gap_interp_xla_m": m(tot["gap_interp_xla"]),
        "general_er_noline": len(noline), "general_er_noline_placed_in_door_counties": sum(1 for f in noline if f["county"] in byc),
        "campuses_added": len(campus_rows), "er_from_cms": sum(1 for f in keep if f["er_src"] == "CMS"),
        "er_confirmed_by_hand": sum(1 for f in keep if f["er_src"] == "confirmed"),
        "jv_dropped": sum(v for k, v in drops.items() if k.startswith("operated by a for-profit") and "[no line]" not in k),
        "stale_extremes": int(tot["stale_extremes"]),
        "fap_checked": len(FAP_CHECKS), "fap_changed": sum(1 for v in FAP_CHECKS.values() if v[0]),
        "gap_cons_cms_m": m(tot["gap_cons_cms"]), "gap_interp_cms_m": m(tot["gap_interp_cms"]), "counties_differ_cms": int(tot["counties_differ_cms"]),
        "elig_min_share": round(100 * tot["elig_min_sum"] / tot["unins_in_differ"], 1),
        "elig_max_share": round(100 * tot["elig_max_sum"] / tot["unins_in_differ"], 1),
        "elig_min_share_raw": round(100 * tot["elig_min_sum_raw"] / tot["unins_in_differ_raw"], 1),
        "elig_max_share_raw": round(100 * tot["elig_max_sum_raw"] / tot["unins_in_differ_raw"], 1),
        "unins_with_door_m": m(tot["unins_with_door"]), "us_unins_u65_m": m(us_unins),
        "median_gap_points": statistics.median(r["max"] - r["min"] for r in differ) if differ else 0,
        "link_methods": dict(methods), "unlinked": len(unlinked),
        "expansion_median_line": {
            "expansion": statistics.median(f["eff"] for f in keep if f["state"] not in NON_EXPANSION),
            "non_expansion": statistics.median(f["eff"] for f in keep if f["state"] in NON_EXPANSION),
            "source": KFF_EXPANSION},
        "showcase": SHOWCASE,
        "top_gap_counties": [r["fips"] for r in sorted(differ, key=lambda r: -r["gap_interp"])[:12]],
        "dropped": dict(drops), "county_placement": dict(nmeth),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    LOG.write_text("\n".join(log_lines))
    log(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
