"""Build the dialysis "time tax" data.

For every 2020 census tract, find the nearest Medicare-certified dialysis center
that offers in-center hemodialysis and estimate the one-way driving time from the
tract's population center, then the travel time a resident would spend per year
if they needed in-center dialysis: 3 sessions a week x 52 weeks x a round trip.

Drive times are real road routes from the public OSRM router for every tract:
  - The table endpoint gives drive times from each tract's population center to its
    nearest centers by straight line (K_CANDIDATES for tracts the old straight-line
    model in _viz/drive_model.json put over LONG_MIN minutes, K_NEAR for the rest);
    the fastest by road is kept. (The old page converted straight-line distance with
    that model, which overstated long rural highway trips, routed some trips across
    lakes, and also overstated short trips; the model is now only used to decide how
    many candidates to try and to report how much routing changed.)
  - Ferries: every chosen trip is checked with the route endpoint; a route that uses a
    ferry is dropped and the next candidate tried (up to K_FERRY_RETRY).
  - A tract whose population center is more than SNAP_KM from a routable road, or whose
    routed trip is over BG_RATIO times the straight-line model, is routed again from each
    of its 2020 block-group population centers, and those block groups count separately.
  - A tract or block group with no ferry-free road route, whose population center is more
    than SNAP_KM from a routable road, or whose only road route takes over MAX_DRIVE_MIN
    one way, gets no drive time and is left out of every average and ranking.
  - Centers the Census batch geocoder could only place at their ZIP code's center are
    tried again (Census single-address geocoder, then OpenStreetMap Nominatim).

Rolls tracts up to counties (population-weighted) and joins CDC/ATSDR SVI 2022 for
households without a vehicle and overall social vulnerability.

Every OSRM answer is cached in _viz/cache/dialysis_osrm.json, so a rebuild only
asks the router about tracts or centers that changed. Calls are spaced at least
1.1 s apart (the demo server's usage policy is one request a second).

Writes data/counties.csv, data/facilities.csv, data/summary.json.
Usage: python3 dialysis-time-tax/scripts/build_data.py   (needs numpy, scipy)
"""
import json
import re
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_viz"))
import vizlib as V  # noqa: E402

LISTING = "https://data.cms.gov/provider-data/api/1/datastore/query/23ew-n7w9/0"
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
OSRM_ROUTE = "https://router.project-osrm.org/route/v1/driving/"
OSRM_CACHE = V.CACHE / "dialysis_osrm.json"
SESSIONS_PER_YEAR = 3 * 52
# tracts the reviewers flagged, reported on the page as before/after examples
EXAMPLES = {"30027030201": "Lewistown, Montana", "27031480200": "Grand Marais, Minnesota"}
FAR_MIN = 30          # one-way minutes considered far for a thrice-weekly trip
LONG_MIN = 20         # straight-line model minutes above which a trip counts as long (more candidates, always ferry-checked)
K_CANDIDATES = 10     # nearest centers (straight line) tried by road for long trips
K_NEAR = 5            # ... and for short ones
K_FERRY_RETRY = 40    # if all of those need a ferry, try this many before calling the tract ferry-only
MAX_DRIVE_MIN = 360   # a road route longer than this one way (Skagway and Haines, AK, via Canada) is no practical trip
SNAP_KM = 10          # population center farther than this from any routable road: no drive time
MAX_COORDS = 100      # coordinates per OSRM table request
MAX_SOURCES = 60
FERRY_PAIRS = 100     # trips checked for a ferry per OSRM route request (chained as waypoints)
BG_RATIO = 3          # routed trip over this many times the straight-line model: route the tract's block groups instead
BG_CENTERS = "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt"
# Alaska's 2019 split of Valdez-Cordova (02261) is newer than the map's county shapes
OLD_VALDEZ = ("02261", ("02063", "02066"))


def svi_without_vehicles():
    """Tract FIPS -> percentile rank of SVI 2022's overall score with the no-vehicle measure taken out
    (SPL_THEMES - EPL_NOVEH), ranked across all tracts with both values, as CDC ranks RPL_THEMES."""
    vals = {}
    for r in V.read_csv(V.fetch(V.SVI_TRACT)):
        spl, ep = V.num(r["SPL_THEMES"]), V.num(r["EPL_NOVEH"])
        if spl is not None and ep is not None:
            vals[r["FIPS"].zfill(11)] = spl - ep
    keys = sorted(vals, key=vals.get)
    n = len(keys)
    out, i = {}, 0
    while i < n:  # ties share the lowest rank
        j = i
        while j + 1 < n and vals[keys[j + 1]] == vals[keys[i]]:
            j += 1
        for k in keys[i:j + 1]:
            out[k] = i / (n - 1)
        i = j + 1
    return out


def facilities():
    rows, offset = [], 0
    while True:
        j = V.get_json(LISTING, {"limit": 1500, "offset": offset})
        rows += j["results"]
        offset += 1500
        if offset >= j["count"]:
            break
    rows = [r for r in rows if r["offers_incenter_hemodialysis"] == "Yes"]
    st = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
          "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
          "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
          "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
          "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
          "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56"}
    rows = [r for r in rows if r["state"] in st]
    geo = V.geocode([{"id": r["cms_certification_number_ccn"], "street": r["address_line_1"], "city": r["citytown"],
                      "state": r["state"], "zip": r["zip_code"]} for r in rows], "dialysis_geocode.json")
    geo = regeocode(rows, geo)
    out = []
    for r in rows:
        g = geo.get(r["cms_certification_number_ccn"])
        if not g:
            continue
        out.append({"ccn": r["cms_certification_number_ccn"], "name": r["facility_name"].title(), "city": r["citytown"].title(),
                    "state": r["state"], "lat": round(g[0], 5), "lon": round(g[1], 5), "geocode": g[2],
                    "stations": r["of_dialysis_stations"], "stars": r["five_star"], "profit": r["profit_or_nonprofit"],
                    "chain": r["chain_organization"], "late_shift": r["late_shift"]})
    print(f"facilities: {len(out)} in-center hemodialysis ({sum(f['geocode'] == 'zip' for f in out)} placed at ZIP centroid, "
          f"{sum(f['geocode'] in ('census', 'osm') for f in out)} found on a second try, {len(rows) - len(out)} not located)")
    return out


# Second try for centers the batch geocoder could only place at their ZIP code's center ---------------------

NOMINATIM = "https://nominatim.openstreetmap.org/search"
REGEO_CACHE = V.CACHE / "dialysis_regeocode.json"
REGEO_MAX_KM = 40  # a match farther than this from the ZIP code's center is treated as wrong


def _clean_street(s):
    s = re.sub(r"[.,]+$", "", s.strip())
    s = re.sub(r"[,\s]+(STE|SUITE|UNIT|BLDG|BUILDING|RM|ROOM|#)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s#\s?\w+$", "", s)
    return s.strip(" ,.")


def regeocode(rows, geo):
    """Retry ZIP-placed centers: Census single-address geocoder with cleaned street strings (line 1, then line 2),
    then OpenStreetMap Nominatim (street, then facility name; 1 request a second). A match is kept only within
    REGEO_MAX_KM of the ZIP code's center and at street level or better. Answers are cached."""
    cache = json.loads(REGEO_CACHE.read_text()) if REGEO_CACHE.exists() else {}
    last = [0.0]

    def get(url, params, pause):
        wait = pause - (time.time() - last[0])
        if wait > 0:
            time.sleep(wait)
        q = url + "?" + urllib.parse.urlencode(params)
        for attempt in range(3):
            try:
                out = subprocess.run(["curl", "-s", "-m", "60", "-A", V.UA["User-Agent"], q],
                                     capture_output=True, text=True, check=True).stdout
                last[0] = time.time()
                return json.loads(out)
            except Exception as e:
                print("  geocode retry", attempt + 1, str(e)[:80])
                time.sleep(5 * (attempt + 1))
        last[0] = time.time()
        return None

    def same_place(hit, r):
        """The OSM match must be in the listed ZIP code or town (a same-named street elsewhere in the metro
        area, like Sunset Drive in Miami Beach for a Kendall address, is not good enough)."""
        a = hit.get("address", {})
        towns = {str(a.get(k, "")).upper() for k in ("city", "town", "village", "hamlet", "municipality", "suburb", "county")}
        return a.get("postcode", "")[:5] == r["zip_code"][:5] or r["citytown"].upper() in towns

    # version 2 of an OSM answer is checked with same_place; older cached OSM answers are asked again
    todo = [r for r in rows if geo.get(r["cms_certification_number_ccn"], (0, 0, ""))[2] == "zip"
            and (r["cms_certification_number_ccn"] not in cache
                 or (cache[r["cms_certification_number_ccn"]] or [0, 0, ""])[2:] == ["osm"])]
    if todo:
        print(f"  re-geocoding {len(todo)} ZIP-placed centers")
    for n, r in enumerate(todo):
        ccn = r["cms_certification_number_ccn"]
        z = geo[ccn]
        ok = lambda la, lo: V.haversine_km(z[0], z[1], la, lo) <= REGEO_MAX_KM  # noqa: E731
        hit = None
        streets = [s for s in dict.fromkeys(_clean_street(x) for x in (r["address_line_1"], r["address_line_2"]))
                   if s and re.match(r"^\d", s) and not re.match(r"^P\.?\s?O\.?\s+BOX", s, re.I)]
        for s in streets:
            j = get("https://geocoding.geo.census.gov/geocoder/locations/address",
                    {"street": s, "city": r["citytown"], "state": r["state"], "zip": r["zip_code"][:5],
                     "benchmark": "Public_AR_Current", "format": "json"}, 0.2)
            m = (j or {}).get("result", {}).get("addressMatches") or []
            if m and ok(m[0]["coordinates"]["y"], m[0]["coordinates"]["x"]):
                hit = [m[0]["coordinates"]["y"], m[0]["coordinates"]["x"], "census"]
                break
        queries = [{"street": s, "city": r["citytown"], "state": r["state"]} for s in streets]
        queries.append({"q": f'{r["facility_name"]}, {r["citytown"]}, {r["state"]}'})
        for q in queries if not hit else []:
            j = get(NOMINATIM, {**q, "countrycodes": "us", "format": "jsonv2", "addressdetails": 1, "limit": 1}, 1.1)
            if j and j[0].get("place_rank", 0) >= 26 and ok(float(j[0]["lat"]), float(j[0]["lon"])) and same_place(j[0], r):
                hit = [float(j[0]["lat"]), float(j[0]["lon"]), "osm", 2]
                break
        cache[ccn] = hit
        if n % 25 == 24:
            REGEO_CACHE.write_text(json.dumps(cache))
            print(f"  {n + 1}/{len(todo)}, {sum(1 for v in cache.values() if v)} found so far")
    REGEO_CACHE.write_text(json.dumps(cache))
    out = dict(geo)
    for ccn, hit in cache.items():
        if hit and ccn in out and out[ccn][2] == "zip":
            out[ccn] = tuple(hit[:3])
    return out


# Road routing (public OSRM demo server, cached and throttled) ----------------

def _k(lat, lon):
    return f"{lat:.5f},{lon:.5f}"


class Router:
    def __init__(self):
        self.c = json.loads(OSRM_CACHE.read_text()) if OSRM_CACHE.exists() else {}
        for part in ("pair", "snap", "route"):
            self.c.setdefault(part, {})
        self.last, self.calls = 0.0, 0

    def save(self):
        tmp = OSRM_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.c, separators=(",", ":")))
        tmp.replace(OSRM_CACHE)

    def _get(self, url):
        for attempt in range(6):
            wait = 1.1 - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            try:
                out = subprocess.run(["curl", "-s", "-m", "120", "-A", V.UA["User-Agent"], url],
                                     capture_output=True, text=True, check=True).stdout
                j = json.loads(out)
            except Exception as e:  # network hiccup or rate limit page; back off
                print("  osrm retry", attempt + 1, str(e)[:80])
                self.last = time.time()
                time.sleep(10 * (attempt + 1))
                continue
            self.last = time.time()
            self.calls += 1
            if self.calls % 25 == 0:
                self.save()
            if j.get("code") in ("Ok", "NoRoute", "NoSegment"):
                return j
            print("  osrm says", j.get("code"), j.get("message"))
            time.sleep(10 * (attempt + 1))
        raise RuntimeError("OSRM keeps failing")

    def pair(self, s, d):
        return self.c["pair"].get(_k(*s) + "|" + _k(*d), "missing")

    def table(self, srcs, dsts):
        coords = list(srcs) + list(dsts)
        url = (OSRM_TABLE + ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in coords)
               + "?sources=" + ";".join(str(i) for i in range(len(srcs)))
               + "&destinations=" + ";".join(str(i) for i in range(len(srcs), len(coords)))
               + "&annotations=duration,distance")
        j = self._get(url)
        if j.get("code") != "Ok":
            raise RuntimeError(f"table failed: {j.get('code')}")
        for i, s in enumerate(srcs):
            self.c["snap"][_k(*s)] = round(j["sources"][i]["distance"])
            for n, d in enumerate(dsts):
                dur, dist = j["durations"][i][n], j["distances"][i][n]
                self.c["pair"][_k(*s) + "|" + _k(*d)] = None if dur is None else [round(dur / 60, 2), round(dist / 1000, 2)]

    def ferry_check(self, pairs):
        """Fill self.c["route"][pair] = [minutes, km, ferry minutes] (or None) for (source, destination) pairs.

        Pairs are chained as waypoints of one route request (s1, d1, s2, d2, ...) so that legs 0, 2, 4...
        are the trips asked about; each leg's steps say whether it uses a ferry. If any leg in a chain
        cannot be routed, the chain is split until each trip is asked about on its own."""
        todo = [(a, b) for a, b in dict.fromkeys(pairs) if _k(*a) + "|" + _k(*b) not in self.c["route"]]
        print(f"  ferry check: {len(todo)} of {len(pairs)} trips not in the cache")
        stack = [todo[i:i + FERRY_PAIRS] for i in range(0, len(todo), FERRY_PAIRS)][::-1]
        while stack:
            chunk = stack.pop()
            coords = [c for pr in chunk for c in pr]
            j = self._get(OSRM_ROUTE + ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in coords)
                          + "?overview=false&steps=true&continue_straight=false")
            if j.get("code") != "Ok" or not j.get("routes"):
                if len(chunk) == 1:
                    self.c["route"][_k(*chunk[0][0]) + "|" + _k(*chunk[0][1])] = None
                else:
                    stack += [chunk[len(chunk) // 2:], chunk[:len(chunk) // 2]]
                continue
            legs = j["routes"][0]["legs"]
            for n, (a, b) in enumerate(chunk):
                leg = legs[2 * n]
                ferry = sum(st["duration"] for st in leg["steps"] if st["mode"] == "ferry")
                self.c["route"][_k(*a) + "|" + _k(*b)] = [round(leg["duration"] / 60, 2), round(leg["distance"] / 1000, 2),
                                                          round(ferry / 60, 2)]
            if self.calls % 50 == 0:
                print(f"  {self.calls} OSRM calls so far")
        self.save()

    def fill(self, jobs):
        """jobs: [(source, [destinations])]; ask the table endpoint for every pair not cached yet."""
        todo = [(s, ds) for s, ds in jobs if any(self.pair(s, d) == "missing" for d in ds)]
        print(f"  routing {len(todo)} of {len(jobs)} tracts not in the cache")
        batch_s, batch_d = [], []
        for s, ds in todo + [(None, [])]:
            union = batch_d + [d for d in ds if d not in batch_d]
            if s is None or len(batch_s) + 1 + len(union) > MAX_COORDS or len(batch_s) >= MAX_SOURCES:
                if batch_s:
                    self.table(batch_s, batch_d)
                    if self.calls % 50 == 0:
                        print(f"  {self.calls} OSRM calls so far")
                batch_s, batch_d = [], []
                union = list(dict.fromkeys(ds))
            if s is not None:
                batch_s.append(s)
                batch_d = union
        self.save()


def road_times(router, ts, fac):
    """Fastest ferry-free road route from each tract (or block group) to any of its candidate centers.

    Sets t["min"] and t["fac"], or t["no_road"] to the reason there is none. Candidates are tried in
    order of table drive time; each unit's current best is checked for a ferry, in batches, and a
    unit whose best uses a ferry moves on to its next candidate."""
    queue = {}
    for t in ts:
        s = (t["lat"], t["lon"])
        t["min"], t["fac"], t["no_road"] = None, None, None
        if router.c["snap"].get(_k(*s), 0) > SNAP_KM * 1000:
            t["no_road"] = "far from a road"
            continue
        opts = []
        for i in t["cands"]:
            p = router.pair(s, (fac[i]["lat"], fac[i]["lon"]))
            if p not in (None, "missing"):
                opts.append((p[0], i))
        if not opts:
            t["no_road"] = "no road route"
            continue
        queue[id(t)] = (t, sorted(opts))
    # Every chosen trip is checked for a ferry (an earlier speed-based shortcut missed north Vashon Island, WA)
    while queue:
        pairs = [((t["lat"], t["lon"]), (fac[o[0][1]]["lat"], fac[o[0][1]]["lon"])) for t, o in queue.values()]
        router.ferry_check(pairs)
        nxt = {}
        for g, (t, opts) in queue.items():
            mins, i = opts[0]
            r = router.c["route"][_k(t["lat"], t["lon"]) + "|" + _k(fac[i]["lat"], fac[i]["lon"])]
            if r is not None and r[2] == 0:
                t["min"], t["fac"] = max(mins, 2.0), i
            elif len(opts) > 1:
                nxt[g] = (t, opts[1:])
            else:
                t["no_road"] = "only by ferry" if r is not None else "no road route"
        queue = nxt


def main():
    fac = facilities()
    minutes, model = V.drive_model()
    rucc = V.rucc()
    svi = V.svi_tracts()
    tracts = [t for t in V.tract_centers() if t["pop"] > 0]
    metro = lambda c: V.is_metro(c, rucc)  # noqa: E731

    svi_x = svi_without_vehicles()
    for t in tracts:
        s = svi(t["geoid"]) or {}
        t["noveh"] = V.num(s.get("E_NOVEH")) or 0
        t["hh"] = V.num(s.get("E_HH")) or 0
        t["svi"] = V.num(s.get("RPL_THEMES"))
        t["svi_x"] = svi_x.get(s.get("FIPS", "").zfill(11))

    def prepare(units):
        km, idx = V.nearest([t["lat"] for t in units], [t["lon"] for t in units],
                            [f["lat"] for f in fac], [f["lon"] for f in fac], k=K_CANDIDATES)
        for t, d, i in zip(units, km, idx):
            t["km"] = float(d[0])
            t["model_min"] = max(minutes(float(d[0]), metro(t["county"])), 2.0)
            t["fac0"] = int(i[0])
            t["cands"] = [int(x) for x in i][:K_CANDIDATES if t["model_min"] > LONG_MIN or t["state"] == "02" else K_NEAR]

    def route(units, what):
        # Long trips first: they matter most if a run is interrupted
        order = sorted(units, key=lambda t: (t["model_min"] <= LONG_MIN and t["state"] != "02", t["state"], t["cands"][0], t["lat"]))
        router.fill([((t["lat"], t["lon"]), [(fac[i]["lat"], fac[i]["lon"]) for i in t["cands"]]) for t in order])
        road_times(router, order, fac)
        # A ferry can be the fastest way to the nearest centers even where a longer road route exists
        # (south Whidbey Island, WA, to Oak Harbor; Plaquemines Parish, LA, to Chalmette), so retry those with more centers.
        retry = [t for t in order if t["no_road"] == "only by ferry"]
        if retry:
            _, idx40 = V.nearest([t["lat"] for t in retry], [t["lon"] for t in retry],
                                 [f["lat"] for f in fac], [f["lon"] for f in fac], k=K_FERRY_RETRY)
            for t, i in zip(retry, idx40):
                t["cands"] = [int(x) for x in i]
            router.fill([((t["lat"], t["lon"]), [(fac[i]["lat"], fac[i]["lon"]) for i in t["cands"]]) for t in retry])
            road_times(router, retry, fac)
            print(f"ferry retry: {len(retry)} {what}, {sum(1 for t in retry if t['no_road'] is None)} found a road route")
        for t in units:
            if t["min"] is not None and t["min"] > MAX_DRIVE_MIN:
                t["min"], t["fac"], t["no_road"] = None, None, "over 6 hours"

    router = Router()
    prepare(tracts)
    route(tracts, "tracts")

    # A big rural tract's population center can fall in empty land between its settlements (Copper River, AK;
    # the Olympic Mountains in Jefferson, WA) or snap to a forest road. Where the center is far from a road, or
    # the routed trip is over BG_RATIO times the straight-line model, route each of its block groups' population
    # centers instead; each block group then counts on its own (residents, and the tract's households split by
    # population share).
    bg_tracts = {t["geoid"]: t for t in tracts
                 if t["no_road"] == "far from a road" or (t["min"] is not None and t["min"] > BG_RATIO * t["model_min"])}
    bgs = []
    for r in V.read_csv(V.fetch(BG_CENTERS)):
        t = bg_tracts.get(r["STATEFP"] + r["COUNTYFP"] + r["TRACTCE"])
        if t and int(r["POPULATION"]) > 0:
            share = int(r["POPULATION"]) / t["pop"]
            bgs.append({**{k: t[k] for k in ("geoid", "county", "state", "svi", "svi_x")}, "bg": r["BLKGRPCE"],
                        "pop": int(r["POPULATION"]), "lat": float(r["LATITUDE"]), "lon": float(r["LONGITUDE"]),
                        "noveh": t["noveh"] * share, "hh": t["hh"] * share,
                        "tract_reason": t["no_road"] or "slow"})
    prepare(bgs)
    route(bgs, "block groups")
    units = [t for t in tracts if t["geoid"] not in bg_tracts] + bgs
    bg_summary = {"tracts": len(bg_tracts), "block_groups": len(bgs), "pop": sum(b["pop"] for b in bgs),
                  "tracts_far_from_road": sum(1 for t in bg_tracts.values() if t["no_road"]),
                  "pop_far_from_road_before": sum(t["pop"] for t in bg_tracts.values() if t["no_road"]),
                  "pop_far_from_road_after": sum(b["pop"] for b in bgs if b["tract_reason"] != "slow" and b["no_road"]),
                  "ratio": BG_RATIO}
    print("block groups:", bg_summary)
    router.save()
    print(f"OSRM calls this run: {router.calls}")
    for t in units:
        t["hours"] = None if t["min"] is None else t["min"] * 2 * SESSIONS_PER_YEAR / 60
    tract_count = len(tracts)
    tracts = units  # everything below works on tracts and, where used, their block groups

    # County roll-up (population-weighted means over tracts with a road route; household counts summed)
    # The map only has the pre-2019 Valdez-Cordova shape, so it also gets a map-only row for its two successors
    agg = defaultdict(lambda: defaultdict(float))
    for t in tracts:
        for c in [t["county"]] + ([OLD_VALDEZ[0]] if t["county"] in OLD_VALDEZ[1] else []):
            a = agg[c]
            a["pop"] += t["pop"]
            a["hh"] += t["hh"]
            a["noveh"] += t["noveh"]
            if t["no_road"]:
                a["noroad_pop"] += t["pop"]
                a["noroad:" + t["no_road"]] += t["pop"]
                continue
            a["road_pop"] += t["pop"]
            a["min_w"] += t["min"] * t["pop"]
            a["hours_w"] += t["hours"] * t["pop"]
            a["far_pop"] += t["pop"] if t["min"] > FAR_MIN else 0
            a["noveh_far"] += t["noveh"] if t["min"] > FAR_MIN else 0
            a["max_min"] = max(a["max_min"], t["min"])
    cty_svi = {r["FIPS"].zfill(5): V.num(r["RPL_THEMES"]) for r in V.read_csv(V.fetch(V.SVI_COUNTY))}
    counties = []
    for c, a in sorted(agg.items()):
        rp = a["road_pop"]
        why = sorted(((v, k[7:]) for k, v in a.items() if k.startswith("noroad:")), reverse=True)
        counties.append({"fips": c, "pop": int(a["pop"]),
                         "one_way_min": round(a["min_w"] / rp, 1) if rp else "",
                         "annual_hours": round(a["hours_w"] / rp) if rp else "",
                         "pct_far": round(100 * a["far_pop"] / rp, 1) if rp else "",
                         "households": int(a["hh"]), "no_vehicle_hh": int(a["noveh"]),
                         "no_vehicle_far_hh": int(a["noveh_far"]),
                         "max_one_way_min": round(a["max_min"]) if rp else "",
                         "pct_no_road": round(100 * a["noroad_pop"] / a["pop"]),
                         "no_road_reason": why[0][1] if why else "",
                         "metro": int(metro(c)), "svi": cty_svi.get(c, ""),
                         "map_only": int(c == OLD_VALDEZ[0])})

    # National summary over tracts with a road route
    noroad = [t for t in tracts if t["no_road"]]
    road = [t for t in tracts if not t["no_road"]]
    pop = np.array([t["pop"] for t in road], float)
    hrs = np.array([t["hours"] for t in road])
    mins = np.array([t["min"] for t in road])
    wmean = lambda v, w: float((v * w).sum() / w.sum())  # noqa: E731
    quart, noveh_q, noveh_qx, far_q, metro_q = {}, {}, {}, {}, {}
    for q, lo, hi in [("Least vulnerable quarter", 0, .25), ("2nd", .25, .5), ("3rd", .5, .75), ("Most vulnerable quarter", .75, 1.01)]:
        g = [t for t in road if t["svi"] is not None and lo <= t["svi"] < hi]
        quart[q] = round(sum(t["pop"] * t["hours"] for t in g) / sum(t["pop"] for t in g))
        noveh_q[q] = round(100 * sum(t["noveh"] for t in g) / sum(t["hh"] for t in g), 1)
        far_q[q] = round(100 * sum(t["pop"] for t in g if t["min"] > FAR_MIN) / sum(t["pop"] for t in g), 1)
        metro_q[q] = round(100 * sum(t["pop"] for t in g if metro(t["county"])) / sum(t["pop"] for t in g), 1)
        gx = [t for t in road if t["svi_x"] is not None and lo <= t["svi_x"] < hi]
        noveh_qx[q] = round(100 * sum(t["noveh"] for t in gx) / sum(t["hh"] for t in gx), 1)
    m_mask = np.array([metro(t["county"]) for t in road])
    def change(g):
        w = np.array([t["pop"] for t in g], float)
        return {"tracts": len(g), "pop": int(w.sum()),
                "mean_model_min": round(wmean(np.array([t["model_min"] for t in g]), w), 1),
                "mean_road_min": round(wmean(np.array([t["min"] for t in g]), w), 1)}
    reasons = defaultdict(int)
    for t in noroad:
        reasons[t["no_road"]] += t["pop"]
    nr_cty = defaultdict(int)
    for t in noroad:
        nr_cty[t["county"]] += t["pop"]
    summary = {
        "facilities": len(fac),
        "tracts": tract_count,
        "zip_placed": sum(f["geocode"] == "zip" for f in fac),
        "regeocoded": sum(f["geocode"] in ("census", "osm") for f in fac),
        "block_group_routing": bg_summary,
        "mean_one_way_min": round(wmean(mins, pop), 1),
        "mean_annual_hours": round(wmean(hrs, pop)),
        "metro_mean_annual_hours": round(wmean(hrs[m_mask], pop[m_mask])),
        "nonmetro_mean_annual_hours": round(wmean(hrs[~m_mask], pop[~m_mask])),
        "people_far": int(pop[mins > FAR_MIN].sum()),
        "pct_people_far": round(100 * float(pop[mins > FAR_MIN].sum() / pop.sum()), 1),
        "no_vehicle_hh": int(sum(t["noveh"] for t in road)),
        "no_vehicle_far_hh": int(sum(t["noveh"] for t in road if t["min"] > FAR_MIN)),
        "hours_by_svi_quarter": quart,
        "pct_no_vehicle_by_svi_quarter": noveh_q,
        # the same, with tracts ranked on SVI minus its own no-vehicle measure (SPL_THEMES - EPL_NOVEH)
        "pct_no_vehicle_by_svi_quarter_without_vehicle_measure": noveh_qx,
        "pct_far_by_svi_quarter": far_q,
        "pct_metro_by_svi_quarter": metro_q,
        "far_minutes": FAR_MIN,
        "sessions_per_year": SESSIONS_PER_YEAR,
        "routing": {
            "long_min": LONG_MIN,
            "candidates_long": K_CANDIDATES,
            "candidates_short": K_NEAR,
            "ferry_retry_candidates": K_FERRY_RETRY,
            # how routing changed the old straight-line estimate, for tracts with a road route
            "long_trips": change([t for t in road if t["model_min"] > LONG_MIN]),
            "short_trips": change([t for t in road if t["model_min"] <= LONG_MIN]),
            "old_model_mean_annual_hours": round(wmean(np.array([t["model_min"] for t in road]) * 2 * SESSIONS_PER_YEAR / 60, pop)),
            "old_model_people_far": int(sum(t["pop"] for t in road if t["model_min"] > FAR_MIN)),
            "examples": [{"place": EXAMPLES[t["geoid"]], "tract": t["geoid"],
                          "model_min": round(t["model_min"]), "model_center": f'{fac[t["fac0"]]["city"]}, {fac[t["fac0"]]["state"]}',
                          "road_min": round(t["min"]), "road_center": f'{fac[t["fac"]]["city"]}, {fac[t["fac"]]["state"]}'}
                         for t in tracts if t["geoid"] in EXAMPLES and "bg" not in t and t["min"] is not None],
            "snap_km": SNAP_KM,
            "max_drive_min": MAX_DRIVE_MIN,
            "source": "OSRM demo server (router.project-osrm.org), OpenStreetMap roads, no traffic",
            "date": time.strftime("%Y-%m-%d"),
        },
        "no_road_tracts": len({t["geoid"] for t in noroad}),
        "no_road_pop": sum(t["pop"] for t in noroad),
        "no_road_pop_by_reason": dict(reasons),
        "no_road_states": sorted({t["state"] for t in noroad}),
        "no_road_top_counties": [[c, p] for c, p in sorted(nr_cty.items(), key=lambda x: -x[1])[:8]],
        "drive_model": {k: model[k] for k in ("metro", "nonmetro")},
    }
    print(json.dumps(summary, indent=2))

    V.write_csv(ROOT / "data" / "counties.csv", counties, list(counties[0].keys()))
    V.write_csv(ROOT / "data" / "facilities.csv", fac,
                ["ccn", "name", "city", "state", "lat", "lon", "stations", "stars", "profit", "chain", "late_shift"])
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return tracts, fac


if __name__ == "__main__":
    main()
