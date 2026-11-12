# The dialysis time tax

Estimated hours a year that driving to in-center hemodialysis would take for the people living in each neighborhood and county, plus households without a car living far from a center. The figures describe residents of each neighborhood (as if they needed dialysis), not current dialysis patients.

**Live:** https://usnish.xyz/dialysis-time-tax/

## Sources

- CMS [Dialysis Facility listing](https://data.cms.gov/provider-data/dataset/23ew-n7w9) (Provider Data Catalog, pulled live at build time), facilities offering in-center hemodialysis, geocoded with the Census Bureau batch geocoder; addresses it missed are retried with the Census single-address geocoder and OpenStreetMap Nominatim (cached in `_viz/cache/dialysis_regeocode.json`, kept only within 40 km of the ZIP code's center), and the rest fall back to the ZIP centroid (`summary.json` → `zip_placed`).
- Census 2020 tract and block-group centers of population.
- CDC/ATSDR SVI 2022 (ACS 2018-2022): households, households with no vehicle, overall vulnerability rank.
- USDA 2023 Rural-Urban Continuum Codes (metro = RUCC 1-3).
- Road drive times: public OSRM demo server (router.project-osrm.org; OpenStreetMap roads, © OpenStreetMap contributors, ODbL; no traffic).
- "Who pays for the ride": CMS booklet [Medicare Coverage of Kidney Dialysis & Kidney Transplant Services](https://www.medicare.gov/publications/10128-medicare-coverage-esrd.pdf) (Product No. 10128, November 2025), section "Transportation to dialysis facilities" (ambulance only when other transport could endanger health; doctor's written order for scheduled repetitive trips; MA plans may cover non-ambulance rides; ask the facility social worker); [Medicare.gov ambulance services](https://www.medicare.gov/coverage/ambulance-services) (nationwide prior authorization for 3+ round trips in 10 days or weekly for 3+ weeks); [MACPAC June 2021 Report to Congress, chapter 5](https://www.macpac.gov/wp-content/uploads/2021/06/Chapter-5-Mandated-Report-on-Non-Emergency-Medical-Transportation.pdf) (42 CFR 431.53 NEMT requirement; full-benefit duals generally get Medicaid NEMT even when Medicare pays for the service; partial-benefit duals do not, footnote 14; ESRD enrollees used NEMT most often of the diagnosis groups studied, FY 2018).
- Amish note under the ranking: Young Center for Anabaptist and Pietist Studies, [twelve largest settlements 2024](https://groups.etown.edu/amishstudies/statistics/twelve-largest-settlements-2024/) (Elkhart/LaGrange and Daviess County, IN) and [technology](https://groups.etown.edu/amishstudies/cultural-practices/technology/) (no car ownership, hired drivers).

Left out on purpose: the reviewer's claim that CMS ended the ESRD Treatment Choices model early was sourced only to a trade-press article, so it is not on the page.

## Method

1. Every tract with residents is routed on real roads with the OSRM table endpoint, from its 2020 population center to its nearest centers by straight line, keeping the fastest drive. Tracts that the old straight-line model (`_viz/drive_model.json`, unchanged) puts over 20 minutes, and all of Alaska, try 10 candidates; the rest try 5.
2. Ferries: every chosen trip is checked with the OSRM route endpoint (an earlier speed-based shortcut missed north Vashon Island, WA) (trips chained as waypoints, 100 per request, so each leg's steps show whether it uses a ferry). A route with a ferry is dropped and the next candidate tried; if all 10 need a ferry, the 40 nearest centers are tried (this found road routes for south Whidbey Island, WA, and Plaquemines Parish, LA).
3. Block groups: a tract whose population center is more than 10 km from a routable road, or whose routed trip is over 3 times the straight-line model, is routed again from each of its 2020 block-group population centers, and each block group then counts on its own (households split by population share). Without this, large rural tracts whose center falls in empty land (Copper River, AK; Jefferson, WA, in the Olympic Mountains; Wendover, UT) were wrongly counted as having no road. `summary.json` → `block_group_routing`.
4. No drive time ("no road route", left out of every average, count and the county ranking; counties where they are the majority are mapped but not ranked): every route to the 40 nearest centers uses a ferry; the population center (of the tract, or of the block group after step 3) is more than 10 km from a routable road; the roads don't connect to any candidate; or the only road route is over 6 hours one way (Skagway, Haines and Hyder, AK, via Canada; Prudhoe Bay). Counts by reason are in `summary.json` → `no_road_pop_by_reason`.
5. Annual hours = one-way minutes (floored at 2) × 2 × 3 sessions a week × 52 weeks / 60. County values are population-weighted means over tracts with a road route. All headline figures are population-weighted means (no medians). Drive times ignore traffic, so city trips are understated most (the page leads its equity comparison with the share more than 30 minutes away, which is less sensitive to this).
6. SVI circularity: the overall SVI rank includes the share of households with no vehicle (EPL_NOVEH), so the no-car gap by SVI quarter is partly built in. The build also ranks tracts on SPL_THEMES − EPL_NOVEH (percentile across all tracts) and reports the no-car shares on that ranking (`pct_no_vehicle_by_svi_quarter_without_vehicle_measure`); the page states both.
7. Map: the county shapes predate Alaska's 2019 split of Valdez-Cordova, so the build writes a map-only `02261` row (Chugach and Copper River combined, `map_only` = 1) that the map draws; the ranking keeps 02063 and 02066 separate and points them at that shape. `counties.csv` → `no_road_reason` is each county's main reason for residents with no drive time.

Every OSRM answer is cached in `_viz/cache/dialysis_osrm.json` (about 200 MB, git-ignored) and calls are spaced at least 1.1 s apart, so a rebuild only asks the router about tracts or centers that changed. A build from an empty cache makes about 2,500 calls and takes roughly 90 minutes; from a warm cache it takes under 2 minutes.

## Rebuild

`python3 dialysis-time-tax/scripts/build_data.py` (needs numpy and scipy; `_viz/drive_model.json` must exist, see `_viz/calibrate_drive.py`).

## What changed (2026-11-12)

- Drive times are now real road routes for every tract instead of the straight-line model. The model was off for long rural trips (Lewistown, MT to Great Falls: 172 min estimated, 115 by road; Grand Marais, MN: 163 min to Ashland, WI across Lake Superior, 154 by road to Duluth) and also overstated short trips (11.9 min average estimated vs 7.4 by road for trips it put at 20 min or less). The plan was to route only long trips, but a 300-tract check during this rebuild, of trips the model put at 10-20 minutes, showed that bias (12.8 min estimated vs 9.2 by road), so everything was routed. `summary.json` → `routing` holds the before/after figures.
- Effect on headline numbers. Old page (straight-line model, older facility list): median 61 hours a year, metro average 69, rural average 143, 22.0M people more than 30 minutes away, 448,000 carless households that far. Now (all averages, after the block-group, ferry and geocoding fixes below): 58 hours a year nationally, metro 47, rural 128, 21.0M people more than 30 minutes away, about 397,000 carless households that far. With today's 6,889 centers the old model would give a national average of 79 hours and 21.9M people (`routing.old_model_*`).
- The old "beyond 150 km" exclusion is replaced by the explicit no-road-route rule above. Alaska boroughs with no road route (Skagway, Haines, Ketchikan, Sitka and others) no longer top the ranking. Chugach and Copper River (Alaska's 2019 split of Valdez-Cordova) are ranked separately and drawn together on the old Valdez-Cordova shape (map-only `02261` row). Chugach's figure (#1 by hours) rests on one routed tract, Valdez, about 5.7 hours each way to Wasilla; Cordova is ferry-only.
- Headline says the figures describe residents of each neighborhood, uses averages throughout, and notes drive times exclude traffic.
- The equity finding (most vulnerable quarter of neighborhoods: 16.1% of households without a vehicle vs 3.4% in the least vulnerable, with shorter average trips) moved to the top; numbers come from `summary.json`.
- New "Who pays for the ride" section, each statement linked to CMS, Medicare.gov or MACPAC.
- Note under the ranking that LaGrange and Daviess, IN (large Amish settlements) rank high on "No car and far away".

## Review fixes (2026-11-12, second pass)

- Block-group routing for tracts whose center is far from a road or whose trip is over 3x the model (75 tracts, 180 block groups, about 212,000 people). Copper River, AK, Jefferson, WA, Wendover, UT, and a rural Imperial, CA, tract now get drive times; only the Dugway block group in Tooele stays without one. "Far from a road" fell from 51,396 to 39,214 people (nearly all roadless western Alaska).
- Every chosen trip is ferry-checked. North Vashon Island moved to "only by ferry", matching south Vashon.
- 470 of the 704 ZIP-placed centers were re-geocoded (Census single-address, then Nominatim with a same-town/ZIP check); 234 remain at ZIP centroids. Molokai's center now sits in Kaunakakai (Kaunakakai tract 53 to 17 min).
- Page: no-car heading wording, "at least ... before traffic, parking or waiting", equity paragraph leads with the share more than 30 min away and states the SVI circularity (16.1% vs 3.4%; 15.0% vs 4.4% with the no-vehicle measure removed), OSM attribution, per-county no-drive-time reason in tooltips, tie-aware ranking, fixed legend bins for the two share measures, stat cards moved under the headline, centers toggle under the map.
