# Clinical trial deserts

Drive time from every community to the nearest site recruiting for an interventional trial in type 2 diabetes, coronary heart disease, cancer or COPD, with breakdowns by race and ethnicity, social vulnerability and rurality.

**Live:** https://usnish.github.io/trial-deserts/

Sources: ClinicalTrials.gov API v2, CDC PLACES (2025 release; KY and PA from 2024), Census 2020 tract population centers, CDC/ATSDR SVI 2022, USDA 2023 Rural-Urban Continuum Codes, OSRM driving times (calibration).

Rebuild: `python3 _viz/calibrate_drive.py` (once), then `python3 trial-deserts/scripts/build_data.py`. Trial data change daily; the page shows the pull date.
