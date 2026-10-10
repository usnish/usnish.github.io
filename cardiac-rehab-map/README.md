# Cardiac rehab participation by state

An interactive map of how many cardiac rehabilitation (CR)–eligible patients actually attend CR, by U.S. state.

**Live:** https://usnish.github.io/cardiac-rehab-map/

Hover a state for its rate, click to pin it, and use the ranked list to compare states. No build step: it's a static page with D3 and the U.S. Atlas state shapes bundled in `vendor/`.

## Data

The map reads two files:

| File | What goes in it |
|---|---|
| `data/state_cr.csv` | One row per state (+ DC): `participation_pct` (0–100), and optionally `eligible` and `participants` counts |
| `data/meta.json` | Population, time period, national rate, source title/URL, and the measure definition shown on the page |

States left blank render as "no data", and the page shows a notice until at least one state has a value.

### From county-level data

CDC's Interactive Atlas of Heart Disease and Stroke publishes county-level CR eligibility and participation for Medicare fee-for-service beneficiaries aged 65+. To roll a county export up to states (eligible-weighted):

```sh
python cardiac-rehab-map/scripts/aggregate_counties.py atlas_export.csv \
  --fips-col cnty_fips --eligible-col eligible --rate-col participation
```

Column names depend on the export; pass whatever the file uses. Note that county estimates in the Atlas are spatially smoothed and small counties may be suppressed, so the state roll-up is an approximation of a direct state-level estimate.

## Measure

Participation = percentage of CR-eligible patients who attended ≥1 outpatient CR session within 365 days of their qualifying event (AMI, CABG, PCI, valve repair/replacement, heart transplant). The Million Hearts goal is ≥70%.

## Licenses

D3, topojson-client and us-atlas are ISC-licensed; see `vendor/LICENSE-*`.
