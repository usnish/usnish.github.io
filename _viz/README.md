# Shared build code for the data visualizations

Not published (Jekyll skips folders starting with `_`).

- `vizlib.py`: cached downloads, nearest-neighbor distances, Census batch geocoding (ZIP-centroid fallback), 2020 tract population centers, CDC/ATSDR SVI 2022, USDA rural-urban codes.
- `calibrate_drive.py`: samples driving times between random tract population centers from the public OSRM router and fits `minutes = a + b × straight-line km` for metro and nonmetro areas. Output: `drive_model.json`, used by `dialysis-time-tax` and `trial-deserts`.
- `cache/`: raw downloads (git-ignored).

Requires Python 3 with `numpy` and `scipy`. The Census Data API now requires a key, so ACS figures come from the CDC/ATSDR SVI files, which are built from the same 2018–2022 ACS estimates.
