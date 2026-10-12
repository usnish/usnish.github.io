# How far a Medicare Advantage network can send you

CMS's maximum drive times for Medicare Advantage networks (2026 HSD Reference File), by county and specialty, compared with the estimated drive from residents 65+ to the nearest provider of that specialty who treats Medicare patients.

**Live:** https://usnish.github.io/ma-network-standards/

Sources: CMS 2026 HSD Reference File (provider and facility time & distance sheets), CMS Doctors and Clinicians national downloadable file (practice ZIP codes), CMS Hospital General Information (acute care and critical access hospitals, Census-geocoded), CMS Nursing Home Provider Information (coordinates), Census 2020 tract population centers, CDC/ATSDR SVI 2022 (population 65+), USDA 2023 Rural-Urban Continuum Codes, OSRM driving times (calibration).

Method: nearest provider to each tract's population center (clinicians at ZIP centroids), straight-line km converted to minutes with `_viz/drive_model.json`, capped at 240 minutes; county figures weighted by population 65+. HSD counties are keyed by SSA code and translated to FIPS through the CMS enrollment file.

Rebuild: `python3 _viz/calibrate_drive.py` (once), then `python3 ma-network-standards/scripts/build_data.py`. Needs `openpyxl`.
