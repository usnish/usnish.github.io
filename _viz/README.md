# Shared build code for the data visualizations

Not published (Jekyll skips folders starting with `_`).

- `vizlib.py`: cached downloads, nearest-neighbor distances, Census batch geocoding (ZIP-centroid fallback), 2020 tract population centers, CDC/ATSDR SVI 2022, USDA rural-urban codes.
- `calibrate_drive.py`: samples driving times between random tract population centers from the public OSRM router and fits `minutes = a + b × straight-line km` for metro and nonmetro areas. Output: `drive_model.json`, used by `dialysis-time-tax` and `trial-deserts`.
- `malib.py`: CMS Medicare Advantage files: Plan Benefit Package tables and service areas, plan crosswalks, monthly enrollment by contract/plan/county (with the SSA-to-FIPS county translation), and the network adequacy (HSD) reference file. Used by `ma-cardiac-rehab`, `ma-network-standards` and `ma-plan-exits`.
- `encrypt_page.py`: password-protects a page for GitHub Pages by encrypting `<page>/_src/` (page plus data) into `<page>/index.html`, which decrypts in the browser. Needs `cryptography`.
- `cache/`: raw downloads (git-ignored).

Requires Python 3 with `numpy` and `scipy`. The Census Data API now requires a key, so ACS figures come from the CDC/ATSDR SVI files, which are built from the same 2018–2022 ACS estimates.
