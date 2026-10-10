"""Shared helpers for the data visualization build scripts.

Folders starting with "_" are not published by Jekyll, so this file and the
download cache under _viz/cache/ stay out of the site.

Requires: numpy, scipy (pip install numpy scipy).
"""
import csv
import io
import json
import math
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

VIZ = Path(__file__).resolve().parent
CACHE = VIZ / "cache"
CACHE.mkdir(exist_ok=True)
EARTH_KM = 6371.0088
UA = {"User-Agent": "usnish.github.io data viz build (contact via github.com/usnish)"}

TRACT_CENTERS = "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR.txt"
SVI_TRACT = "https://svi.cdc.gov/Documents/Data/2022/csv/states/SVI_2022_US.csv"
SVI_COUNTY = "https://svi.cdc.gov/Documents/Data/2022/csv/states_counties/SVI_2022_US_county.csv"
RUCC = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv?v=41138"
ZCTA_GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_zcta_national.zip"
GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
OSRM = "https://router.project-osrm.org/route/v1/driving/"

# 50 states + DC (the county shapes on the maps cover these)
STATE_FIPS = {f"{i:02d}" for i in list(range(1, 57))} - {"03", "07", "14", "43", "52"}


def fetch(url, name=None, data=None, timeout=300):
    """Download url into the cache (once) and return the local path."""
    path = CACHE / (name or Path(urllib.parse.urlparse(url).path).name)
    if not path.exists():
        req = urllib.request.Request(url, data=data, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            path.write_bytes(r.read())
    return path


def get_json(url, params=None, timeout=120):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except UnicodeDecodeError:  # e.g. USDA files are Latin-1 ("Doña Ana")
        with open(path, newline="", encoding="latin-1") as f:
            return list(csv.DictReader(f))


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def num(x):
    try:
        v = float(str(x).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return None if v != v or v == -999 else v  # SVI uses exactly -999 for missing


# Geography ------------------------------------------------------------------

def tract_centers():
    """2020 tract centers of population: [{geoid, county, pop, lat, lon}] (2020 county codes)."""
    out = []
    for r in read_csv(fetch(TRACT_CENTERS)):
        if r["STATEFP"] not in STATE_FIPS:
            continue
        out.append({"geoid": r["STATEFP"] + r["COUNTYFP"] + r["TRACTCE"], "county": r["STATEFP"] + r["COUNTYFP"],
                    "tractce": r["TRACTCE"], "state": r["STATEFP"], "pop": int(r["POPULATION"]),
                    "lat": float(r["LATITUDE"]), "lon": float(r["LONGITUDE"])})
    return out


def svi_tracts():
    """CDC/ATSDR SVI 2022 (ACS 2018-2022) by tract, keyed by GEOID and by state+tract code.

    Connecticut tracts are coded by planning region in 2022 data but by county in
    the 2020 tract centers, so the state+tract-code key is used as a fallback.
    """
    by_geoid, by_st_tract = {}, {}
    for r in read_csv(fetch(SVI_TRACT)):
        g = r["FIPS"].zfill(11)
        by_geoid[g] = r
        by_st_tract.setdefault(g[:2] + g[5:], []).append(r)
    by_st_tract = {k: v[0] for k, v in by_st_tract.items() if len(v) == 1}
    return lambda geoid: by_geoid.get(geoid) or by_st_tract.get(geoid[:2] + geoid[5:])


def rucc():
    """County FIPS -> 2023 Rural-Urban Continuum Code (1-3 metro, 4-9 nonmetro)."""
    out = {}
    for r in read_csv(fetch(RUCC, "rucc2023.csv")):
        if r["Attribute"] == "RUCC_2023":
            out[r["FIPS"].zfill(5)] = int(r["Value"])
    return out


def is_metro(county, rucc_map):
    """Metro (RUCC 1-3) test for a 2020 county code.

    Connecticut's 2023 codes use planning regions; of its 2020 counties only
    Litchfield (09005) and Windham (09015) fall in the nonmetro regions.
    """
    if county.startswith("09"):
        return county not in ("09005", "09015")
    return rucc_map.get(county, 9) <= 3


def zcta_centroids():
    with zipfile.ZipFile(fetch(ZCTA_GAZ)) as z:
        text = z.read(z.namelist()[0]).decode("utf-8")
    rows = csv.reader(io.StringIO(text), delimiter="\t")
    head = [h.strip() for h in next(rows)]  # the last header is padded with spaces
    i, la, lo = head.index("GEOID"), head.index("INTPTLAT"), head.index("INTPTLONG")
    return {r[i]: (float(r[la]), float(r[lo])) for r in rows}


def geocode(records, cache_name):
    """Census batch geocoder with ZIP-centroid fallback.

    records: [{id, street, city, state, zip}] -> {id: (lat, lon, method)}
    """
    path = CACHE / cache_name
    done = {k: tuple(v) for k, v in json.loads(path.read_text()).items()} if path.exists() else {}
    missed = CACHE / ("missed_" + cache_name)
    known_misses = set(json.loads(missed.read_text())) if missed.exists() else set()
    if all(r["id"] in done or r["id"] in known_misses for r in records):
        return done
    partial = CACHE / ("partial_" + cache_name)
    out = json.loads(partial.read_text()) if partial.exists() else {}
    out.update({k: v for k, v in done.items() if v[2] == "address"})
    todo = [r for r in records if r["id"] not in out and r["id"] not in done]
    for i in range(0, len(todo), 2000):
        chunk = todo[i:i + 2000]
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in chunk:
            w.writerow([r["id"], r["street"], r["city"], r["state"], r["zip"][:5]])
        boundary = "----vizlib"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\nPublic_AR_Current\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"a.csv\"\r\n"
                f"Content-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n--{boundary}--\r\n").encode()
        req = urllib.request.Request(GEOCODER, data=body, headers={**UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=900) as resp:
                    text = resp.read().decode("utf-8", "replace")
                break
            except Exception as e:  # the geocoder occasionally times out; retry
                print("  geocoder retry", attempt + 1, e)
                time.sleep(10)
        else:
            raise RuntimeError("Census geocoder failed")
        for row in csv.reader(io.StringIO(text)):
            if len(row) > 5 and row[2] == "Match" and row[5]:
                lon, lat = map(float, row[5].split(","))
                out[row[0]] = (lat, lon, "address")
        print(f"  geocoded {min(i + 2000, len(todo))}/{len(todo)}")
        (CACHE / ("partial_" + cache_name)).write_text(json.dumps(out))
    zc = zcta_centroids()
    for r in records:
        if r["id"] not in out and r["zip"][:5] in zc:
            out[r["id"]] = (*zc[r["zip"][:5]], "zip")
    out = {**done, **out}
    path.write_text(json.dumps(out))
    missed.write_text(json.dumps(sorted(known_misses | {r["id"] for r in records if r["id"] not in out})))
    return {k: tuple(v) for k, v in out.items()}


# Distance and drive time ----------------------------------------------------

def _xyz(lat, lon):
    lat, lon = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]


def nearest(from_lat, from_lon, to_lat, to_lon, k=1):
    """Great-circle km and index of the k nearest targets for each origin."""
    tree = cKDTree(_xyz(np.asarray(to_lat), np.asarray(to_lon)))
    chord, idx = tree.query(_xyz(np.asarray(from_lat), np.asarray(from_lon)), k=k)
    return 2 * EARTH_KM * np.arcsin(np.clip(chord / 2, 0, 1)), idx


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def osrm_minutes(lat1, lon1, lat2, lon2):
    """One driving route from the public OSRM demo server (light use only)."""
    # curl rather than urllib: the macOS system Python's SSL can't handshake with this server
    url = f"{OSRM}{lon1:.5f},{lat1:.5f};{lon2:.5f},{lat2:.5f}?overview=false"
    j = json.loads(subprocess.run(["curl", "-s", "-m", "60", "-A", UA["User-Agent"], url],
                                  capture_output=True, text=True, check=True).stdout)
    if j.get("code") != "Ok":
        return None
    return j["routes"][0]["duration"] / 60


def drive_model():
    """Load the calibrated straight-line -> drive-minutes model (see calibrate_drive.py)."""
    m = json.loads((VIZ / "drive_model.json").read_text())

    def minutes(km, metro):
        p = m["metro" if metro else "nonmetro"]
        return p["a"] + p["b"] * km
    return minutes, m
