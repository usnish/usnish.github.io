"""Build the data for "Same company, different state: who gets a dialysis chair after 5 pm".

Source: CMS Provider Data Catalog, dataset 23ew-n7w9 "Dialysis Facility - Listing
by Facility" (the current file plus archived snapshots). Its "Late Shift" column is
defined in the CMS data dictionary as "a shift starting at 5:00 P.M. or later".

Computes, for units that offer in-center hemodialysis (HD):
  1. National share of units with a late shift, and the share of HD patients who
     dialyze at such a unit (weighted by the column
     "Number of adult HD patients with KT/V data"; NOT the Kt/V availability code,
     which looks numeric but is a footnote code) and by stations.
  2. The same by state (territories kept apart).
  3. Each chain's share by state (the same company in different markets).
  4. For every 2020 census tract population center in the contiguous US, the
     great-circle distance to the nearest in-center HD unit and to the nearest unit
     with a late shift; population shares living beyond 0..100 miles.
  5. Share of current units with a late shift by certification year, and by ESRD Network.
  6. Unit-level churn in the late shift between the 2020-10-31 archive snapshot
     and the current file (units matched on CMS Certification Number), plus the
     national share in each annual snapshot since 2023.

Geocodes: the Census batch geocoder via _viz/vizlib.py, seeded from the
dialysis-time-tax cache (_viz/cache/dialysis_geocode.json) so only new units are
looked up; ZIP centroid when an address does not match.

Writes data/summary.json, states.csv, chains.csv, chain_states.csv, dist_cdf.csv,
trend.csv, churn.json, facilities.csv.
Usage: python3 dialysis-after-five/scripts/build_data.py   (needs numpy, scipy)
"""
import csv
import io
import json
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
SUB = "dialysis-after-five"
(V.CACHE / SUB).mkdir(exist_ok=True)

META = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/23ew-n7w9"
ARCHIVE = "https://data.cms.gov/provider-data/sites/default/files/dataset-archives/theme/dialysis-facilities/dialysis-facilities_{}.zip"
# 2020-10-31 is the earliest snapshot whose facility file has the late-shift column in CSV form.
# The 2021-04-12 and 2022-04-27 snapshots carry a byte-identical copy of that same file, so they are skipped.
BASE_SNAPSHOT = "2020-10-31"
TREND_SNAPSHOTS = ["2020-10-31", "2023-04-26", "2024-04-24", "2025-04-23", "2026-04-22"]

KTV = "Number of adult HD patients with KT/V data"
TERRITORIES = {"PR", "GU", "VI", "AS", "MP"}
MILE_KM = 1.609344
MIN_CHAIN_STATE = 20  # units of a chain in a state for its row to be shown

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
CHAINS = {"DaVita": "DaVita", "Fresenius Medical Care": "Fresenius", "US Renal Care, Inc.": "US Renal Care",
          "Dialysis Clinic, Inc.": "DCI", "American Renal Associates": "American Renal Associates",
          "Independent": "Independent"}


def chain_label(raw):
    raw = (raw or "").strip()
    for k, v in CHAINS.items():
        if raw.lower() == k.lower() or raw.lower().startswith(v.lower()):
            return v
    if raw.upper().startswith("FRESENIUS"):
        return "Fresenius"
    if raw.upper().startswith("US RENAL") or raw.upper().startswith("U.S. RENAL"):
        return "US Renal Care"
    if raw.upper().startswith("DIALYSIS CLINIC"):
        return "DCI"
    if raw.upper().startswith("AMERICAN RENAL"):
        return "American Renal Associates"
    if raw == "" or raw.lower() in ("independent", "none"):
        return "Independent"
    return "Other"


def yes(v):
    return str(v).strip().lower() in ("yes", "1", "true", "y")


def num(v):
    x = V.num(v)
    return x or 0.0


def cert_year(v):
    """Year from the 'Certification Date' column (MM/DD/YYYY); None when blank."""
    v = (v or "").strip()
    try:
        return int(v.split("/")[-1][:4])
    except ValueError:
        return None


CERT_BINS = [("before 2000", None, 1999), ("2000-2009", 2000, 2009), ("2010-2014", 2010, 2014),
             ("2015-2019", 2015, 2019), ("2020 or later", 2020, None)]


def normalize(rows):
    """Common fields across file vintages (column names changed in 2023 and 2024)."""
    h = list(rows[0].keys())
    ccn = h[0]  # "Provider Number" (2020), "Certification Number" (2023), "CMS Certification Number (CCN)"
    zipc = "ZIP Code" if "ZIP Code" in h else "Zip"
    city = "City/Town" if "City/Town" in h else "City"
    out = []
    for r in rows:
        out.append({
            "ccn": r[ccn].strip().zfill(6), "state": r["State"].strip(), "chain_raw": r["Chain Organization"],
            "chain": chain_label(r["Chain Organization"]), "late": yes(r["Late Shift"]),
            "incenter": yes(r["Offers in-center hemodialysis"]), "stations": num(r["# of Dialysis Stations"]),
            "pts": num(r.get(KTV, "")), "street": r.get("Address Line 1", ""), "city": r.get(city, ""),
            "zip": r.get(zipc, "").strip()[:5].zfill(5), "name": r.get("Facility Name", ""),
            "network": r.get("Network", "").strip(), "cert_year": cert_year(r.get("Certification Date", "")),
            "home": yes(r.get("Offers peritoneal dialysis", "")) or yes(r.get("Offers home hemodialysis training", "")),
        })
    return out


def read_rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def current_file():
    meta = V.get_json(META)
    url = next(d["downloadURL"] for d in meta["distribution"] if d["downloadURL"].endswith(".csv"))
    path = V.fetch(url, f"{SUB}/DFC_FACILITY_{meta['modified']}.csv")
    return meta, url, normalize(read_rows(path.read_text(encoding="utf-8-sig")))


def snapshot(date):
    path = V.fetch(ARCHIVE.format(date), f"{SUB}/dialysis-facilities_{date}.zip")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        name = next((n for n in names if n.endswith("DFC_FACILITY.csv")), None) or \
            next(n for n in names if n.endswith("23ew-n7w9.csv"))
        text = z.read(name).decode("utf-8-sig", "replace")
    return normalize(read_rows(text))


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def shares(units):
    n = len(units)
    late = [u for u in units if u["late"]]
    p = sum(u["pts"] for u in units)
    s = sum(u["stations"] for u in units)
    return {"units": n, "late_units": len(late), "pct_units": pct(len(late), n),
            "patients": int(p), "late_patients": int(sum(u["pts"] for u in late)),
            "pct_patients": pct(sum(u["pts"] for u in late), p),
            "stations": int(s), "pct_stations": pct(sum(u["stations"] for u in late), s)}


def eta2(units, key):
    """Share of the variance in the unit-level late-shift indicator explained by a grouping.

    Returns (eta squared, omega squared). Omega squared corrects for the number of
    groups (51 states vs 7 chain groups), so the two groupings compare fairly.
    """
    y = np.array([u["late"] for u in units], float)
    groups = defaultdict(list)
    for u, v in zip(units, y):
        groups[key(u)].append(v)
    sst = ((y - y.mean()) ** 2).sum()
    ssb = sum(len(g) * (np.mean(g) - y.mean()) ** 2 for g in groups.values())
    k, n = len(groups), len(y)
    msw = (sst - ssb) / (n - k)
    return round(float(ssb / sst), 3), round(float((ssb - (k - 1) * msw) / (sst + msw)), 3)


def main():
    meta, url, rows = current_file()
    ic = [u for u in rows if u["incenter"]]
    print(f"current file {meta['modified']}: {len(rows)} units, {len(ic)} in-center HD, "
          f"{sum(u['late'] for u in ic)} with a late shift")
    nat = shares(ic)
    states_only = [u for u in ic if u["state"] not in TERRITORIES]
    # For "What could change this": patients whose unit has no evening shift, and those whose unit
    # has neither an evening shift nor home dialysis (CMS columns "Offers peritoneal dialysis" and
    # "Offers home hemodialysis training"). Same units and patient weight as `national`.
    def part(us):
        return {"units": len(us), "pct_units": pct(len(us), len(ic)), "patients": int(sum(u["pts"] for u in us)),
                "pct_patients": pct(sum(u["pts"] for u in us), sum(u["pts"] for u in ic))}
    alternatives = {"no_evening": part([u for u in ic if not u["late"]]),
                    "home": part([u for u in ic if u["home"]]),
                    "no_evening_no_home": part([u for u in ic if not u["late"] and not u["home"]])}

    # States -------------------------------------------------------------------
    by_state = defaultdict(list)
    for u in ic:
        by_state[u["state"]].append(u)
    state_rows = []
    for st, us in by_state.items():
        if st not in STATE_NAMES:
            print("  unknown state code", st, len(us))
            continue
        cm = Counter(u["chain"] for u in us)
        r = {"state": st, "name": STATE_NAMES[st], "territory": int(st in TERRITORIES), **shares(us),
             "davita_units": cm["DaVita"], "fresenius_units": cm["Fresenius"]}
        state_rows.append(r)
    state_rows.sort(key=lambda r: (r["territory"], -(r["pct_patients"] or 0)))

    # Chains, and chain x state ------------------------------------------------
    by_chain = defaultdict(list)
    for u in states_only:
        by_chain[u["chain"]].append(u)
    chain_rows = sorted(({"chain": c, **shares(us)} for c, us in by_chain.items()), key=lambda r: -r["units"])
    cs_rows = []
    for c, us in by_chain.items():
        g = defaultdict(list)
        for u in us:
            g[u["state"]].append(u)
        for st, su in g.items():
            if len(su) >= 10:
                cs_rows.append({"chain": c, "state": st, "name": STATE_NAMES[st], **shares(su),
                                "shown": int(len(su) >= MIN_CHAIN_STATE)})
    cs_rows.sort(key=lambda r: (r["chain"], -(r["pct_units"] or 0)))

    # do the two big chains move together across states?
    dv = {r["state"]: r["pct_units"] for r in cs_rows if r["chain"] == "DaVita" and r["shown"]}
    fr = {r["state"]: r["pct_units"] for r in cs_rows if r["chain"] == "Fresenius" and r["shown"]}
    both = sorted(set(dv) & set(fr))
    corr = float(np.corrcoef([dv[s] for s in both], [fr[s] for s in both])[0, 1]) if len(both) > 2 else None
    # rank (Spearman) correlation: the Pearson value leans on Washington, high for both
    rank_corr = float(spearmanr([dv[s] for s in both], [fr[s] for s in both])[0]) if len(both) > 2 else None
    # spread of each big chain's state shares (rows shown)
    spread = {}
    for c in ("DaVita", "Fresenius"):
        rr = [r for r in cs_rows if r["chain"] == c and r["shown"]]
        hi, lo = max(rr, key=lambda r: r["pct_units"]), min(rr, key=lambda r: r["pct_units"])
        spread[c] = {"states_shown": len(rr), "high_state": hi["state"], "high_pct": hi["pct_units"],
                     "high_late": hi["late_units"], "high_units": hi["units"],
                     "low_state": lo["state"], "low_pct": lo["pct_units"], "low_late": lo["late_units"],
                     "low_units": lo["units"]}
    # Share of unit-level variance explained by each grouping. The company figure depends on how
    # chains are grouped (folding small chains into "Other" shrinks it), and state, company and
    # ESRD Network overlap, so no ratio between them is reported.
    (es, os_), (ec, oc) = eta2(states_only, lambda u: u["state"]), eta2(states_only, lambda u: u["chain"])
    ecr, ocr = eta2(states_only, lambda u: (u["chain_raw"] or "").strip().lower() or "independent")
    en, on = eta2(states_only, lambda u: u["network"])
    variance = {"eta2_state": es, "omega2_state": os_, "eta2_chain": ec, "omega2_chain": oc,
                "chain_groups": len({u["chain"] for u in states_only}),
                "eta2_chain_raw": ecr, "omega2_chain_raw": ocr,
                "chain_raw_groups": len({(u["chain_raw"] or "").strip().lower() or "independent" for u in states_only}),
                "eta2_network": en, "omega2_network": on}
    by_net = defaultdict(list)
    for u in states_only:
        by_net[u["network"]].append(u)
    networks = {n: {"states": sorted({u["state"] for u in us}), **shares(us)} for n, us in by_net.items()}

    # Certification year: do newer units add an evening shift as they fill? ----
    cert = []
    for lab, lo, hi in CERT_BINS:
        us = [u for u in ic if u["cert_year"] is not None and (lo is None or u["cert_year"] >= lo)
              and (hi is None or u["cert_year"] <= hi)]
        sh = shares(us)
        cert.append({"certified": lab, "units": sh["units"], "late_units": sh["late_units"], "pct_units": sh["pct_units"],
                     "median_patients": float(np.median([u["pts"] for u in us])),
                     "median_stations": float(np.median([u["stations"] for u in us]))})
    cert_blank = sum(1 for u in ic if u["cert_year"] is None)

    # Distance -----------------------------------------------------------------
    contig = [u for u in ic if u["state"] not in TERRITORIES | {"AK", "HI"}]
    cache = V.CACHE / "dialysis_after_five_geocode.json"
    if not cache.exists() and (V.CACHE / "dialysis_geocode.json").exists():
        shutil.copy(V.CACHE / "dialysis_geocode.json", cache)  # reuse the time-tax geocodes; only new units are looked up
    geo = V.geocode([{"id": u["ccn"], "street": u["street"], "city": u["city"], "state": u["state"], "zip": u["zip"]}
                     for u in contig], cache.name)
    placed = [u for u in contig if u["ccn"] in geo]
    for u in placed:
        u["lat"], u["lon"], u["geo"] = geo[u["ccn"]]
    late_units = [u for u in placed if u["late"]]
    tracts = [t for t in V.tract_centers() if t["state"] not in ("02", "15") and t["pop"] > 0]
    tl, tn = np.array([t["lat"] for t in tracts]), np.array([t["lon"] for t in tracts])
    pop = np.array([t["pop"] for t in tracts], float)
    d_any, _ = V.nearest(tl, tn, [u["lat"] for u in placed], [u["lon"] for u in placed])
    d_eve, _ = V.nearest(tl, tn, [u["lat"] for u in late_units], [u["lon"] for u in late_units])
    d_any, d_eve = d_any / MILE_KM, d_eve / MILE_KM
    total = pop.sum()
    cdf = []
    for m in range(0, 101):
        cdf.append({"miles": m, "pct_beyond_any": round(100 * pop[d_any > m].sum() / total, 2),
                    "pct_beyond_evening": round(100 * pop[d_eve > m].sum() / total, 2)})

    def wmedian(d):
        o = np.argsort(d)
        c = np.cumsum(pop[o])
        return float(d[o][np.searchsorted(c, total / 2)])

    tstate = np.array([STATE_FIPS[t["state"]] for t in tracts])
    st_dist = {}
    for st in set(tstate):
        mk = tstate == st
        p = pop[mk].sum()
        st_dist[st] = {"pct_beyond30_any": round(100 * pop[mk & (d_any > 30)].sum() / p, 1),
                       "pct_beyond30_evening": round(100 * pop[mk & (d_eve > 30)].sum() / p, 1)}
    for r in state_rows:
        r.update(st_dist.get(r["state"], {"pct_beyond30_any": None, "pct_beyond30_evening": None}))
    rucc = V.rucc()
    metro = np.array([V.is_metro(t["county"], rucc) for t in tracts])

    def wmed_mask(d, mk):
        o = np.argsort(d[mk])
        c = np.cumsum(pop[mk][o])
        return float(d[mk][o][np.searchsorted(c, c[-1] / 2)])

    dist = {"tracts": len(tracts), "population": int(total), "units_placed": len(placed),
            "units_zip_centroid": sum(u["geo"] == "zip" for u in placed),
            "units_unplaced": len(contig) - len(placed), "late_units_placed": len(late_units),
            "late_units_unplaced": sum(u["late"] for u in contig if u["ccn"] not in geo),
            "median_any_mi": round(wmedian(d_any), 1), "median_evening_mi": round(wmedian(d_eve), 1),
            "metro_median_evening_mi": round(wmed_mask(d_eve, metro), 1),
            "nonmetro_median_evening_mi": round(wmed_mask(d_eve, ~metro), 1),
            "metro_median_any_mi": round(wmed_mask(d_any, metro), 1),
            "nonmetro_median_any_mi": round(wmed_mask(d_any, ~metro), 1),
            "people_beyond30_evening": int(pop[d_eve > 30].sum()),
            "people_beyond30_any": int(pop[d_any > 30].sum())}
    for m in (10, 20, 30, 50):
        dist[f"pct_beyond{m}_any"] = cdf[m]["pct_beyond_any"]
        dist[f"pct_beyond{m}_evening"] = cdf[m]["pct_beyond_evening"]

    # Trend and churn ----------------------------------------------------------
    trend = []
    snaps = {}
    check_2020 = None
    for d in TREND_SNAPSHOTS:
        everything = snapshot(d)
        if d == BASE_SNAPSHOT:  # Crouch et al. 2024 report 16.0% of all facilities in 2020 CMS data
            check_2020 = {"facilities": len(everything), "late": sum(u["late"] for u in everything),
                          "pct_all_facilities": pct(sum(u["late"] for u in everything), len(everything))}
        s = [u for u in everything if u["incenter"]]
        snaps[d] = s
        sh = shares(s)
        trend.append({"snapshot": d, "units": sh["units"], "late_units": sh["late_units"],
                      "pct_units": sh["pct_units"], "pct_patients": sh["pct_patients"]})
    trend.append({"snapshot": meta["modified"], "units": nat["units"], "late_units": nat["late_units"],
                  "pct_units": nat["pct_units"], "pct_patients": nat["pct_patients"]})
    base = {u["ccn"]: u for u in snaps[BASE_SNAPSHOT]}
    now = {u["ccn"]: u for u in ic}
    all_now = {u["ccn"] for u in rows}
    kept = [c for c in base if c in now]
    dropped = [c for c in kept if base[c]["late"] and not now[c]["late"]]
    added = [c for c in kept if not base[c]["late"] and now[c]["late"]]
    stayed = [c for c in kept if base[c]["late"] and now[c]["late"]]
    gone = [c for c in base if c not in now]
    gone_late = [c for c in gone if base[c]["late"]]
    new = [c for c in now if c not in base]
    new_late = [c for c in new if now[c]["late"]]
    churn = {"from": BASE_SNAPSHOT, "to": meta["modified"],
             "units_then": len(base), "late_then": sum(u["late"] for u in base.values()),
             "units_now": len(now), "late_now": sum(u["late"] for u in now.values()),
             "units_in_both": len(kept), "late_in_both_then": sum(base[c]["late"] for c in kept),
             "kept_late": len(stayed), "dropped_late": len(dropped), "added_late": len(added),
             "units_gone": len(gone), "late_units_gone": len(gone_late),
             "late_units_gone_still_listed": sum(c in all_now for c in gone_late),
             "units_new": len(new), "new_with_late": len(new_late),
             "pct_new_with_late": pct(len(new_late), len(new)),
             "pct_gone_late": pct(len(gone_late), len(gone))}
    by_chain_churn = defaultdict(Counter)
    for c in dropped:
        by_chain_churn[now[c]["chain"]]["dropped"] += 1
    for c in added:
        by_chain_churn[now[c]["chain"]]["added"] += 1
    churn["by_chain"] = {k: dict(v) for k, v in by_chain_churn.items()}

    # Facilities for the dot map (contiguous US, rounded) ----------------------
    fac = [{"lat": round(u["lat"], 3), "lon": round(u["lon"], 3), "late": int(u["late"])} for u in placed]

    # Write --------------------------------------------------------------------
    V.write_csv(DATA / "states.csv", state_rows, list(state_rows[0].keys()))
    V.write_csv(DATA / "chains.csv", chain_rows, list(chain_rows[0].keys()))
    V.write_csv(DATA / "chain_states.csv", cs_rows, list(cs_rows[0].keys()))
    V.write_csv(DATA / "dist_cdf.csv", cdf, list(cdf[0].keys()))
    V.write_csv(DATA / "trend.csv", trend, list(trend[0].keys()))
    V.write_csv(DATA / "facilities.csv", fac, ["lat", "lon", "late"])
    (DATA / "churn.json").write_text(json.dumps(churn, indent=1))
    summary = {
        "source_modified": meta["modified"], "source_url": url, "built": str(np.datetime64("today")),
        "national": nat, "national_states_only": shares(states_only), "alternatives": alternatives,
        "states_50_dc": sum(1 for r in state_rows if not r["territory"]),
        "chain_spread": spread, "davita_fresenius_state_corr": round(corr, 2) if corr is not None else None,
        "davita_fresenius_state_rank_corr": round(rank_corr, 2) if rank_corr is not None else None,
        "davita_fresenius_states_compared": len(both), "variance_explained": variance,
        "esrd_networks": {n: networks[n] for n in sorted(networks, key=lambda k: int(k) if k.isdigit() else 99)},
        "by_certification_year": cert, "cert_year_blank_units": cert_blank,
        "min_chain_state_units": MIN_CHAIN_STATE, "check_2020_all_facilities": check_2020, "distance": dist, "churn": churn,
        "pts_column": KTV, "pts_blank_units": sum(1 for u in ic if u["pts"] == 0),
    }
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("national", "chain_spread", "davita_fresenius_state_corr",
                                               "davita_fresenius_state_rank_corr", "variance_explained",
                                               "by_certification_year")}, indent=1))
    print(json.dumps(dist, indent=1))
    print(json.dumps({k: v for k, v in churn.items() if k != "by_chain"}))
    print(trend)
    for r in state_rows:
        print(r["state"], r["pct_patients"], r["pct_units"], r["pct_stations"], r["units"])
    for r in cs_rows:
        if r["shown"]:
            print(r["chain"], r["state"], r["late_units"], "/", r["units"], r["pct_units"])
    tot = sum(p.stat().st_size for p in DATA.iterdir())
    print(f"data/ total {tot / 1024:.0f} KB")


if __name__ == "__main__":
    main()
