"""Fit straight-line distance -> driving minutes, separately for metro and nonmetro areas.

Samples random pairs of 2020 tract population centers 1-150 km apart, asks the
public OSRM demo router for the driving time (1 request/second), and fits
minutes = a + b * km by least squares. Writes _viz/drive_model.json, which the
dialysis and clinical trial builds use instead of routing every tract.

Usage: python3 _viz/calibrate_drive.py [pairs_per_group=200]
"""
import json
import random
import sys
import time

import numpy as np

import vizlib as V

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
random.seed(7)
tracts = [t for t in V.tract_centers() if t["pop"] > 0]
rucc = V.rucc()
lat = np.array([t["lat"] for t in tracts])
lon = np.array([t["lon"] for t in tracts])
groups = {"metro": [i for i, t in enumerate(tracts) if rucc.get(t["county"], 9) <= 3],
          "nonmetro": [i for i, t in enumerate(tracts) if rucc.get(t["county"], 9) >= 4]}

model = {}
for name, idx in groups.items():
    pairs = []
    while len(pairs) < N:
        i = random.choice(idx)
        # pick a destination among the 400 nearest tracts so distances span 1-150 km
        d, nn = V.nearest([lat[i]], [lon[i]], lat, lon, k=400)
        j = int(random.choice(nn[0][1:]))
        km = V.haversine_km(lat[i], lon[i], lat[j], lon[j])
        if not 1 <= km <= 150:
            continue
        try:
            mins = V.osrm_minutes(lat[i], lon[i], lat[j], lon[j])
        except Exception as e:
            print("osrm error", e)
            time.sleep(5)
            continue
        time.sleep(1.05)
        if mins:
            pairs.append((km, mins))
            if len(pairs) % 50 == 0:
                print(name, len(pairs))
    km, mins = np.array(pairs).T
    b, a = np.polyfit(km, mins, 1)
    pred = a + b * km
    r2 = 1 - ((mins - pred) ** 2).sum() / ((mins - mins.mean()) ** 2).sum()
    model[name] = {"a": round(a, 3), "b": round(b, 4), "r2": round(r2, 3), "n": len(pairs),
                   "median_abs_err_min": round(float(np.median(abs(mins - pred))), 1),
                   "km_range": [round(km.min(), 1), round(km.max(), 1)]}
    print(name, model[name])

model["source"] = "OSRM demo server (router.project-osrm.org) driving times between random 2020 tract population centers"
model["date"] = time.strftime("%Y-%m-%d")
(V.VIZ / "drive_model.json").write_text(json.dumps(model, indent=2) + "\n")
