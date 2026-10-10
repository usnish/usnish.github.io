# Cardiac rehab eligibility by county

A county map of the heart conditions that qualify patients for cardiac rehabilitation (CR): how many Medicare beneficiaries had a CR-qualifying event, how often they're hospitalized for heart attack, coronary heart disease or heart failure, how many eligible patients actually attend CR, and how common coronary heart disease is among all adults.

Static page (D3 + us-atlas county shapes in `vendor/`), no build step:

```sh
python3 -m http.server 8000
```

## Measures

| Measure | Period | Population | Source |
|---|---|---|---|
| CR-eligible events per 1,000 | 2019–2020* | Medicare FFS 65+ | CDC Atlas of Heart Disease and Stroke (CMS CCW claims) |
| Heart attack hospitalizations per 1,000 | 2019–2021 | Medicare FFS 65+, age-standardized, smoothed | CDC Atlas (CMS MEDPAR) |
| Coronary heart disease hospitalizations per 1,000 | 2019–2021 | same | CDC Atlas (CMS MEDPAR) |
| Heart failure hospitalizations per 1,000 | 2019–2021 | same | CDC Atlas (CMS MEDPAR) |
| CR participation among eligible (%) | 2019–2020* | Medicare FFS 65+ | CDC Atlas (CMS CCW claims) |
| Coronary heart disease prevalence (%) | 2023 | All adults 18+, age-adjusted, modeled | CDC PLACES 2025 release (BRFSS) |

\*CDC labels the CR measures both "2018–2019" and "2019–2020"; the Atlas menu lists the year as 2019.

CR-eligible events follow the Million Hearts surveillance definition: heart attack, bypass surgery, PCI/stenting, heart valve repair or replacement, heart or heart–lung transplant.

## Refreshing the data

```sh
python3 scripts/fetch_data.py
```

Pulls every measure from the CDC Atlas API (`heart-stroke-atlas.cdc.gov/api/api/data`) and the PLACES Socrata API, and rewrites `data/counties.csv` and `data/measures.json`. To add an Atlas measure, add its theme IDs to `ATLAS_MEASURES` (IDs are in `https://heart-stroke-atlas.cdc.gov/api/api/config`). The Atlas API returned HTTP 405 for several days in October 2026 before recovering; if it fails, try again later.

## Known gaps

- Medicare measures exclude Medicare Advantage enrollees (about 40% of beneficiaries in 2019–2021).
- PLACES 2025 has no Kentucky or Pennsylvania estimates and reports Connecticut by planning region, which doesn't match the 2017-vintage county shapes.
- Counties with too few events are suppressed and shown in gray.

## Licenses

D3, topojson-client and us-atlas are ISC-licensed; see `vendor/LICENSE-*`.
