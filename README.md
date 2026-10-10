# Cardiac rehab participation map

An interactive map of how many cardiac rehabilitation (CR)–eligible patients actually attend CR, across U.S. states and regions.

**Live:** https://usnish.github.io/cardiac-rehab-map/

Hover a state for its rate, click to pin it, switch between data years, and use the ranked list to compare. No build step: it's a static page with D3 and the U.S. Atlas state shapes bundled in `vendor/`. To preview locally:

```sh
python3 -m http.server 8000
```

## Data

| Year | Geography | Source |
|---|---|---|
| 2016 (default) | 9 U.S. Census divisions | Ritchey MD et al., *Circ Cardiovasc Qual Outcomes* 2020, Table 2 (CDC analysis of Medicare FFS claims, beneficiaries 65+) |
| 1997 | 50 states + DC | Suaya JA et al., *Circulation* 2007, as tabulated in Gaalema DE et al., *J Cardiopulm Rehabil Prev* 2014 |

CDC publishes the 2016 figures by Census division only, so every state in a division shows the division's rate. Division totals sum to 365,271 eligible / 89,287 participants; the remaining 832 eligible (40 participants) had no division and appear only in the national 24.4%.

The two years use different eligibility definitions (1997: heart attack or bypass surgery; 2016: also PCI, valve procedures and heart transplant), so they aren't directly comparable.

Files:

| File | What goes in it |
|---|---|
| `data/datasets.json` | One entry per toggle: label, geography (`state` or `division`), CSV path, population, period, national rate, source and definition text |
| `data/state_cr.csv` | 1997 state rates: `participation_pct` (0–100), optional `eligible` and `participants` |
| `data/division_cr_2016.csv` | 2016 Census-division rates with eligible and participant counts |
| `data/state_divisions.csv` | State FIPS → Census division lookup |

### Newer, state-level data

CDC's [Interactive Atlas of Heart Disease and Stroke](https://heart-stroke-atlas.cdc.gov/) has 2019 county-level CR participation (Health Care Delivery and Insurance → Cardiac Rehabilitation Use, theme 91), with a State map breakdown. As of October 2026 its data service returns HTTP 405 for every request, including from the Atlas's own page. Once it works again, export the county (or state) table and roll it up:

```sh
python scripts/aggregate_counties.py atlas_export.csv \
  --fips-col cnty_fips --eligible-col eligible --rate-col participation \
  --out data/state_cr_2019.csv
```

then add a `"geography": "state"` entry for that file to `data/datasets.json`. County estimates in the Atlas are spatially smoothed and small counties may be suppressed, so the roll-up approximates a direct state estimate.

## Measure

Participation = percentage of CR-eligible patients who attended ≥1 outpatient CR session within 365 days of their qualifying event. The Million Hearts goal is ≥70%.

## Licenses

D3, topojson-client and us-atlas are ISC-licensed; see `vendor/LICENSE-*`.
