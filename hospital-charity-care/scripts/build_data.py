"""Build the nonprofit hospital charity care data.

From CMS's Hospital Provider Cost Report (HCRIS), take every nonprofit short-term
acute care and critical access hospital and its reported charity care (at cost).
The main year is CMS's 2024 file: cost-report years that began between October
2023 and September 2024. The 2023 file (years beginning October 2022 to September
2023) is read too, to compare the same hospitals across the two years.

Each hospital is matched to its state's Medicaid expansion status from KFF's
state table (implementation dates), compared with the dates its cost-report year
covers. For context, the build also computes a rough, partial estimate of each
hospital's federal income tax exemption: 21% of positive net income. State and
local exemptions, tax-exempt bonds and deductible donations are not included.

Hospitals are geocoded with the Census geocoder and placed in counties; county
uninsured and poverty rates come from CDC/ATSDR SVI 2022 (ACS 2018-2022).

Writes data/hospitals.csv, data/states.csv, data/counties.csv, data/summary.json.
Usage: python3 hospital-charity-care/scripts/build_data.py   (needs numpy, scipy)
"""
import html
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

HCRIS = {
    2024: "https://data.cms.gov/sites/default/files/2026-10/46b1f5a0-a9dd-4431-beee-2ee7194b4135/CostReport_2024_Final.csv",
    2023: "https://data.cms.gov/sites/default/files/2026-10/e48e1326-aeeb-4ad4-acf6-a506871b6d20/CostReport_2023_Final.csv",
}
YEAR, PREV = 2024, 2023
HOSP_INFO = ("https://data.cms.gov/provider-data/sites/default/files/resources/"
             "893c372430d9d71a1c52737d01239d47_1785189955/Hospital_General_Information.csv")
KFF = "https://www.kff.org/health-reform/state-indicator/state-activity-around-expanding-medicaid-under-the-affordable-care-act/"
KFF_CACHE = "kff_medicaid_expansion_status.html"
KFF_ELIG = "https://www.kff.org/health-reform/state-indicator/medicaid-income-eligibility-limits-for-adults-as-a-percent-of-the-federal-poverty-level/"
KFF_ELIG_CACHE = "kff_medicaid_adult_eligibility.html"
UNWINDING_START = date(2023, 4, 1)  # first month states could end Medicaid coverage after the pandemic pause
FED_RATE = 0.21
MAX_MARGIN = 0.5  # net income above half of total costs is almost always a one-time gain or a reporting error
FULL_YEAR = (350, 380)  # days; the same-hospital comparison uses full-year reports only
NONPROFIT = {"1": "Nonprofit (church)", "2": "Nonprofit (other)"}
TYPES = {"STH": "Short-term acute care", "CAH": "Critical access"}
STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
STATES = set(STATE_NAMES.values())
NAMES = {v: k for k, v in STATE_NAMES.items()}
# Census Bureau South region (used only to check whether the expansion gap is just a regional one)
SOUTH = {"DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX"}
# The rest of the Worksheet S-10 uncompensated care block; all blank means the hospital filled in none of it
S10_OTHER = ("Total Bad Debt Expense", "Cost of Uncompensated Care", "Total Unreimbursed and Uncompensated Care")
GROUPS = {"non":"Did not expand Medicaid", "exp": "Expanded Medicaid", "late": "Expanded during these years"}


def mdy(s):
    m, d, y = map(int, s.split("/"))
    return date(y, m, d)


def expansion_status():
    """KFF state table -> ({state: implementation date or None}, 'as of' label)."""
    text = V.fetch(KFF, KFF_CACHE).read_text(encoding="utf-8", errors="replace")
    table = text[text.index("<table"):text.index("</table>")]
    head = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    assert head[1:3] == ["Status of Medicaid Expansion Decision", "Expansion Implementation Date"], head
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 3 and cells[0] in STATE_NAMES:
            out[STATE_NAMES[cells[0]]] = mdy(cells[2]) if cells[1] == "Adopted" else None
            assert cells[1] in ("Adopted", "Not Adopted"), cells
    assert len(out) == 51, len(out)
    as_of = re.search(r"<figure>\s*<h3>([^<]+)</h3>", text)
    return out, (as_of.group(1).strip() if as_of else "")


def kff_table(url, cache):
    """A KFF State Health Facts table -> ([[cells]] by state, 'as of' label, {state: footnote})."""
    text = V.fetch(url, cache).read_text(encoding="utf-8", errors="replace")
    table = text[text.index("<table"):text.index("</table>")]
    rows = {}
    for row in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells and cells[0] in STATE_NAMES:
            rows[STATE_NAMES[cells[0]]] = cells[1:]
    as_of = re.search(r"<figure>\s*<h3>([^<]+)</h3>", text)
    notes = {STATE_NAMES[m.group(1)]: json.loads('"' + m.group(2) + '"') for m in
             re.finditer(r'\["any","Region","","([^"]+)","Footnote","((?:[^"\\]|\\.)*)"', text) if m.group(1) in STATE_NAMES}
    return rows, (as_of.group(1).strip() if as_of else ""), notes


def adult_eligibility():
    """KFF Medicaid income limit for adults without children, as a share of the poverty line, by state."""
    rows, as_of, notes = kff_table(KFF_ELIG, KFF_ELIG_CACHE)
    assert len(rows) == 51, len(rows)
    return {s: round(100 * float(c[1])) for s, c in rows.items()}, as_of, notes


def hospitals(year):
    rows = V.read_csv(V.fetch(HCRIS[year], f"hcris_{year}.csv"))
    latest = {}
    for r in rows:
        if r["Type of Control"] not in NONPROFIT or r["CCN Facility Type"] not in TYPES or r["State Code"] not in STATES:
            continue
        ccn = r["Provider CCN"]
        if ccn not in latest or mdy(r["Fiscal Year End Date"]) > mdy(latest[ccn]["Fiscal Year End Date"]):
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
        # HCRIS public files store no zeros (a blank can mean $0 or a line never filled in), so a blank
        # charity care line is treated as missing, not as $0, and left out of every median, share and change
        charity = V.num(r["Cost of Charity Care"])
        reported = charity is not None
        s10_blank = all(V.num(r[c]) is None for c in S10_OTHER)
        tax = FED_RATE * max(net, 0.0)
        begin, end = mdy(r["Fiscal Year Begin Date"]), mdy(r["Fiscal Year End Date"])
        out.append({
            "charity_reported": reported, "s10_blank": s10_blank,
            "ccn": r["Provider CCN"], "name": r["Hospital Name"].title(), "street": r["Street Address"],
            "city": r["City"].title(), "state": r["State Code"], "zip": r["Zip Code"][:5],
            "type": TYPES[r["CCN Facility Type"]],
            "beds": int(V.num(r["Number of Beds"]) or 0), "begin": begin, "end": end,
            "fy_begin": begin.strftime("%m/%d/%Y"), "fy_end": end.strftime("%m/%d/%Y"),
            "total_costs": round(costs), "net_income": round(net),
            "charity_care": round(charity) if reported else None,
            "fed_tax_est": round(tax), "pct": 100 * charity / costs if reported else float("nan"),
            "charity_pct_costs": round(100 * charity / costs, 2) if reported else None,
        })
    print(f"{year}: {len(out)} nonprofit STH/CAH ({dropped} dropped for missing costs or income, "
          f"{len(outliers)} for net income above {MAX_MARGIN:.0%} of costs)")
    return out, dropped, outliers


def one_line_geocode(rows):
    """Census single-address geocoder, street + city + state only (no ZIP). {ccn: (lat, lon, 'address')}"""
    path = V.CACHE / "charity_care_cms_address_geocode.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    for ccn, r in rows.items():
        if ccn in done:
            continue
        q = urllib.parse.urlencode({"street": r["Address"], "city": r["City/Town"], "state": r["State"],
                                    "benchmark": "Public_AR_Current", "format": "json"})
        m = V.get_json("https://geocoding.geo.census.gov/geocoder/locations/address?" + q)["result"]["addressMatches"]
        done[ccn] = [m[0]["coordinates"]["y"], m[0]["coordinates"]["x"], "address"] if m else None
    path.write_text(json.dumps(done))
    return {k: tuple(v) for k, v in done.items() if v and k in rows}


def county_names():
    """(state, COUNTY NAME) -> 2020 county FIPS, from the SVI tract file's names."""
    out = {}
    for r in V.read_csv(V.fetch(V.SVI_TRACT)):
        if r["ST_ABBR"] != "CT":  # SVI 2022 uses Connecticut planning regions, not the 2020 counties
            out[(r["ST_ABBR"], re.sub(r" (County|Parish|Borough|Census Area|Municipality|City and Borough)$", "",
                                      r["COUNTY"]).upper())] = r["STCNTY"].zfill(5)
    ct = ["FAIRFIELD", "HARTFORD", "LITCHFIELD", "MIDDLESEX", "NEW HAVEN", "NEW LONDON", "TOLLAND", "WINDHAM"]
    out.update({("CT", n): f"090{2 * i + 1:02d}" for i, n in enumerate(ct)})  # 09001 ... 09015
    return out


def classify(h, impl):
    """Was Medicaid expansion in effect for this hospital's whole cost-report year?"""
    d = impl[h["state"]]
    if d is None or d > h["end"]:
        return "non"
    return "exp" if d <= h["begin"] else "partial"


def med(a):
    return round(float(np.median(a)), 2) if len(a) else None


def main():
    impl, kff_as_of = expansion_status()
    elig, elig_as_of, elig_notes = adult_eligibility()
    hosp, dropped, outliers = hospitals(YEAR)
    prev, _, _ = hospitals(PREV)

    # A state's group: all of its hospitals' report years fully before or after expansion, or a mix
    for rows in (hosp, prev):
        by_state = defaultdict(set)
        for h in rows:
            h["exp_h"] = classify(h, impl)
            by_state[h["state"]].add(h["exp_h"])
        for h in rows:
            s = by_state[h["state"]]
            h["expansion"] = "exp" if s == {"exp"} else "non" if s == {"non"} else "late"
    late_states = sorted({h["state"] for h in hosp if h["expansion"] == "late"})
    late_either = sorted({h["state"] for h in hosp + prev if h["expansion"] == "late"})
    print("states that expanded during the main year:", late_states, "| during either year:", late_either)

    geo = V.geocode([{"id": h["ccn"], "street": h["street"], "city": h["city"], "state": h["state"], "zip": h["zip"]}
                     for h in hosp], "hospital_geocode.json")
    # Some cost-report addresses are PO boxes with a PO-box-only ZIP, which neither the geocoder nor the
    # ZIP fallback can place; retry those with the street address in CMS's hospital file
    hgi = {r["Facility ID"]: r for r in V.read_csv(V.fetch(HOSP_INFO, "Hospital_General_Information.csv"))}
    retry = [h["ccn"] for h in hosp if h["ccn"] not in geo and h["ccn"] in hgi]
    geo = {**geo, **one_line_geocode({c: hgi[c] for c in retry})}
    # Last resort: the county named in CMS's hospital file
    by_name = county_names()
    for h in hosp:
        r = hgi.get(h["ccn"])
        if h["ccn"] not in geo and r:
            h["county_by_name"] = by_name.get((r["State"], r["County/Parish"].upper()), "")
    missing_geo = [h["ccn"] for h in hosp if h["ccn"] not in geo and not h.get("county_by_name")]
    print("placed by county name:", [h["ccn"] for h in hosp if h.get("county_by_name")], "| not placed:", missing_geo)
    located = [h for h in hosp if h["ccn"] in geo]
    for h in hosp:
        h["geocode"] = geo[h["ccn"]][2] if h["ccn"] in geo else ""
        h["county"] = h["county_uninsured"] = h["county_poverty150"] = ""
    for h in located:
        h["lat"], h["lon"] = round(geo[h["ccn"]][0], 5), round(geo[h["ccn"]][1], 5)

    # County context from SVI tracts, rolled up to 2020 counties
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
    _, idx = V.nearest([h["lat"] for h in located], [h["lon"] for h in located],
                       [t["lat"] for t in tracts], [t["lon"] for t in tracts])
    for h, i in zip(located, idx):
        h["county"] = tracts[int(i)]["county"]
        h["county_uninsured"] = cmap.get(h["county"], {}).get("pct_uninsured", "")
        h["county_poverty150"] = cmap.get(h["county"], {}).get("pct_poverty150", "")
    for h in hosp:
        if h.get("county_by_name"):
            h["county"], h["geocode"] = h["county_by_name"], "county name"
            h["county_uninsured"] = cmap.get(h["county"], {}).get("pct_uninsured", "")
            h["county_poverty150"] = cmap.get(h["county"], {}).get("pct_poverty150", "")

    # Same hospital, prior year (full-year reports in both years only)
    full = lambda h: FULL_YEAR[0] <= (h["end"] - h["begin"]).days + 1 <= FULL_YEAR[1]  # noqa: E731
    pmap = {h["ccn"]: h for h in prev}
    for h in hosp:
        p = pmap.get(h["ccn"])
        h["charity_prev"] = p["charity_care"] if p else ""
        h["fy_begin_prev"] = p["fy_begin"] if p else ""

    # ---- Summary numbers
    ex = np.array([h["expansion"] for h in hosp])
    rep = np.array([h["charity_reported"] for h in hosp])  # charity care line filled in
    ch = np.array([h["charity_care"] if h["charity_reported"] else 0.0 for h in hosp], float)  # blanks add nothing to sums
    costs = np.array([h["total_costs"] for h in hosp], float)
    tax = np.array([h["fed_tax_est"] for h in hosp], float)
    pct = np.array([h["pct"] for h in hosp])
    unins = np.array([h["county_uninsured"] if h["county_uninsured"] != "" else np.nan for h in hosp])
    pov = np.array([h["county_poverty150"] if h["county_poverty150"] != "" else np.nan for h in hosp])
    unins_r, pov_r = np.where(rep, unins, np.nan), np.where(rep, pov, np.nan)  # for charity care comparisons
    south = np.array([h["state"] in SOUTH for h in hosp])
    taxed = tax > 0
    taxed_r = taxed & rep  # positive income and a charity care figure to compare with

    by_exp = {}
    for g in GROUPS:
        m = ex == g
        st = sorted({h["state"] for h, k in zip(hosp, m) if k})
        by_exp[g] = {
            "label": GROUPS[g], "states": st, "n_states": len(st), "hospitals": int(m.sum()),
            "charity_reported": int((m & rep).sum()), "charity_not_reported": int((m & ~rep).sum()),
            "pct_hospitals": round(100 * m.sum() / len(hosp), 1),
            "charity_total": round(float(ch[m].sum())), "pct_charity_dollars": round(100 * ch[m].sum() / ch.sum(), 1),
            "pct_costs": round(100 * costs[m].sum() / costs.sum(), 1),
            "median_charity_pct_costs": med(pct[m & rep]),
            "aggregate_charity_pct_costs": round(100 * ch[m].sum() / costs[m & rep].sum(), 2),
            "median_county_uninsured": med(unins[m & ~np.isnan(unins)]),
            "median_county_poverty150": med(pov[m & ~np.isnan(pov)]),
            "n_south": int((m & south).sum()), "states_south": sorted(set(st) & SOUTH),
            "median_charity_pct_costs_south": med(pct[m & south & rep]),
            "median_charity_pct_costs_not_south": med(pct[m & ~south & rep]),
            "n_not_south_reported": int((m & ~south & rep).sum()),
            "with_positive_income": int((m & taxed_r).sum()),
            "pct_profitable_tax_above_charity": round(100 * float(((ch < tax) & taxed_r & m).sum() / (taxed_r & m).sum()), 1),
        }
    two = (ex == "exp") | (ex == "non")
    mw = sps.mannwhitneyu(pct[(ex == "non") & rep], pct[(ex == "exp") & rep])

    # States, for the strip chart
    states = []
    for s in sorted(STATES):
        m = np.array([h["state"] == s for h in hosp])
        if not m.any():
            continue
        states.append({"state": s, "name": NAMES[s], "group": ex[m][0], "hospitals": int(m.sum()),
                       "charity_reported": int((m & rep).sum()),
                       "median_charity_pct_costs": med(pct[m & rep]),
                       "aggregate_charity_pct_costs": round(100 * ch[m].sum() / costs[m & rep].sum(), 2),
                       "charity_total": round(float(ch[m].sum())),
                       "expansion_date": impl[s].isoformat() if impl[s] else ""})
    st_non = [s["median_charity_pct_costs"] for s in states if s["group"] == "non"]
    st_exp = [s["median_charity_pct_costs"] for s in states if s["group"] == "exp"]

    # County quartiles (cutoffs from all hospitals), medians within each expansion group
    def quartiles(vals, name):
        qs = np.nanquantile(vals, [.25, .5, .75])
        lo_hi = [(-1, qs[0]), (qs[0], qs[1]), (qs[1], qs[2]), (qs[2], 101)]
        out = []
        for i, (lo, hi) in enumerate(lo_hi):
            q = (vals > lo) & (vals <= hi)
            row = {"quarter": i + 1, "range": [round(float(np.nanmin(vals[q])), 1), round(float(np.nanmax(vals[q])), 1)],
                   "hospitals": int(q.sum()), "median_all": med(pct[q])}
            for g in ("exp", "non"):
                row[g] = {"hospitals": int((q & (ex == g)).sum()), "median": med(pct[q & (ex == g)])}
            out.append(row)
        rho = {}
        for g in ("exp", "non"):
            m = (ex == g) & ~np.isnan(vals)
            r = sps.spearmanr(vals[m], pct[m])
            rho[g] = {"rho": round(float(r.statistic), 2), "p": float(f"{r.pvalue:.2g}"), "hospitals": int(m.sum())}
        print(name, json.dumps(out), rho)
        return out, rho

    q_unins, rho_unins = quartiles(unins_r, "uninsured")
    q_pov, rho_pov = quartiles(pov_r, "poverty150")

    # Same hospitals, both years (both reports full-year with the charity care line filled in)
    pairs_all = [(h, pmap[h["ccn"]]) for h in hosp if h["ccn"] in pmap and full(h) and full(pmap[h["ccn"]])]
    pairs = [(h, p) for h, p in pairs_all if h["charity_reported"] and p["charity_reported"]]

    def change(ps):
        a = sum(p["charity_care"] for _, p in ps)
        b = sum(h["charity_care"] for h, _ in ps)
        ca = sum(p["total_costs"] for _, p in ps)
        cb = sum(h["total_costs"] for h, _ in ps)
        return {"hospitals": len(ps), "charity_prev": a, "charity": b, "charity_change_pct": round(100 * (b / a - 1), 1),
                "costs_change_pct": round(100 * (cb / ca - 1), 1),
                "share_prev": round(100 * a / ca, 2), "share": round(100 * b / cb, 2),
                "median_pct_prev": med([p["pct"] for _, p in ps]), "median_pct": med([h["pct"] for h, _ in ps]),
                "pct_hospitals_up": round(100 * sum(h["charity_care"] > p["charity_care"] for h, p in ps) / len(ps), 1)}
    chg = {"all": change(pairs)}
    for g in ("exp", "non"):
        chg[g] = change([(h, p) for h, p in pairs if h["expansion"] == g and p["expansion"] == g])
    chg["pairs_not_reported"] = len(pairs_all) - len(pairs)
    # Hospitals whose earlier report year began after the unwinding started: both years fall inside it
    chg["prev_in_unwinding"] = change([(h, p) for h, p in pairs if p["begin"] >= UNWINDING_START])
    chg["excluded_states"] = sorted({h["state"] for h, p in pairs if h["expansion"] != p["expansion"] or h["expansion"] == "late"})

    begins = [h["begin"] for h in hosp]
    pbegins = [h["begin"] for h in prev]
    summary = {
        "year": YEAR, "prev_year": PREV,
        "fy_begin_range": [min(begins).isoformat(), max(begins).isoformat()],
        "prev_fy_begin_range": [min(pbegins).isoformat(), max(pbegins).isoformat()],
        "fy_end_range": [min(h["end"] for h in hosp).isoformat(), max(h["end"] for h in hosp).isoformat()],
        "kff_as_of": kff_as_of, "unwinding_start": UNWINDING_START.isoformat(),
        "fed_rate": FED_RATE, "hospitals": len(hosp), "hospitals_prev": len(prev),
        "dropped_missing": dropped, "excluded_outliers": len(outliers), "max_margin": MAX_MARGIN,
        "not_geocoded": len(missing_geo), "geocoded_at_zip": sum(h["geocode"] == "zip" for h in hosp),
        "county_by_name": sum(h["geocode"] == "county name" for h in hosp),
        "with_positive_income": int(taxed_r.sum()), "no_positive_income": int((~taxed).sum()),
        "charity_not_reported": int((~rep).sum()),
        "charity_not_reported_s10_blank": int(sum(not h["charity_reported"] and h["s10_blank"] for h in hosp)),
        "charity_not_reported_positive_income": int((taxed & ~rep).sum()),
        "fed_tax_est_total": round(float(tax.sum())), "charity_total": round(float(ch.sum())),
        "fed_tax_est_total_reported": round(float(tax[rep].sum())),
        "charity_total_profitable": round(float(ch[taxed].sum())),
        "pct_profitable_tax_above_charity": round(100 * float(((ch < tax) & taxed_r).sum() / taxed_r.sum()), 1),
        "n_profitable_tax_above_charity": int(((ch < tax) & taxed_r).sum()),
        "median_charity_pct_costs": med(pct[rep]),
        "per_100_dollars": med(pct[rep]),
        "by_expansion": by_exp,
        "late_states": late_states,
        "ratio_median_non_to_exp": round(by_exp["non"]["median_charity_pct_costs"] / by_exp["exp"]["median_charity_pct_costs"], 1),
        "mann_whitney_p": float(f"{mw.pvalue:.2g}"),
        "state_medians": {"non_min": min(st_non), "non_max": max(st_non), "exp_min": min(st_exp), "exp_max": max(st_exp),
                          "non_median": med(st_non), "exp_median": med(st_exp),
                          "non_states_above_exp_median": sorted(s["state"] for s in states if s["group"] == "non" and s["median_charity_pct_costs"] > med(st_exp)),
        "non_states_below_exp_median": sorted(s["state"] for s in states if s["group"] == "non" and s["median_charity_pct_costs"] <= med(st_exp)),
        "non_states_above_all_exp": sorted(s["state"] for s in states if s["group"] == "non" and s["median_charity_pct_costs"] > max(st_exp))},
    "non_expansion_adult_limits": {s: {"pct_poverty_line": elig[s], "note": elig_notes.get(s, "")}
                                   for s in by_exp["non"]["states"]},
    "kff_eligibility_as_of": elig_as_of,
        "two_group_hospitals": int(two.sum()),
        "by_county_uninsured": q_unins, "spearman_uninsured": rho_unins,
        "by_county_poverty": q_pov, "spearman_poverty": rho_pov,
        "change": chg, "full_year_days": FULL_YEAR,
    }
    print(json.dumps({k: v for k, v in summary.items() if k not in ("by_county_uninsured", "by_county_poverty")}, indent=1))
    cols = ["ccn", "name", "city", "state", "type", "beds", "fy_begin", "fy_end", "total_costs", "net_income",
            "charity_care", "charity_reported", "fed_tax_est", "charity_pct_costs", "charity_prev", "fy_begin_prev", "expansion",
            "county", "county_uninsured", "county_poverty150"]
    out_rows = [{**h, "charity_reported": "true" if h["charity_reported"] else "false"} for h in hosp]
    V.write_csv(ROOT / "data" / "hospitals.csv", sorted(out_rows, key=lambda h: h["ccn"]), cols)
    V.write_csv(ROOT / "data" / "states.csv", states, ["state", "name", "group", "hospitals", "charity_reported", "median_charity_pct_costs",
                                                         "aggregate_charity_pct_costs", "charity_total", "expansion_date"])
    V.write_csv(ROOT / "data" / "counties.csv", counties, ["fips", "pct_uninsured", "pct_poverty150"])
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
