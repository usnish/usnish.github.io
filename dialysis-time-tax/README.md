# The dialysis time tax

Estimated hours a year people on in-center hemodialysis spend driving to treatment, by county, plus households without a car living far from a center.

**Live:** https://usnish.github.io/dialysis-time-tax/

Sources: CMS Dialysis Facility listing (Provider Data Catalog), Census 2020 tract population centers, CDC/ATSDR SVI 2022, USDA 2023 Rural-Urban Continuum Codes, OSRM driving times (calibration). Method: straight-line distance from each tract's population center to the nearest in-center hemodialysis facility, converted to drive minutes with `_viz/drive_model.json`; annual hours = one-way × 2 × 156 sessions.

Rebuild: `python3 _viz/calibrate_drive.py` (once), then `python3 dialysis-time-tax/scripts/build_data.py`.
