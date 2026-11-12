# Same company, different state: who gets a dialysis chair after 5 pm

Whether people on in-center hemodialysis can get a chair after the workday: the share of patients whose unit runs a shift starting at 5 pm or later, by state; the same company's evening offering across states; how far Americans live from an evening unit compared with any unit; and unit-level change since 2020.

**Live:** https://usnish.xyz/dialysis-after-five/

## Findings (CMS file updated 2026-10-22)

- 1,131 of 6,959 units offering in-center HD (16.3%) have a late shift; weighted by patients, 21.8% (by stations, 19.3%).
- Patient-weighted by state: Washington 78.0%, New York 47.1%, Colorado 46.2%, California 27.1% ... Georgia 6.7%, South Carolina 6.5%, Minnesota 4.9%, North Dakota 0%.
- Same company: DaVita 31 of 47 units in Washington vs 2 of 95 in North Carolina; Fresenius 15 of 29 in Washington, 31 of 65 in New York vs 3 of 69 in South Carolina. Across 28 states where both have at least 20 units, their state shares move together (Spearman rank correlation 0.57; Pearson 0.73, but 0.54 without Washington). Omega squared of the unit-level late-shift flag: state 7.2%, ESRD Network 5.6%, company 0.5% with the 7 page groups or 2.7% with all 30 raw chain names. No ratio is reported: the company figure depends on the grouping, and state, company and network overlap.
- Distance (lower 48 + DC, straight line, population-weighted): median 2.2 mi to any unit vs 6.6 mi to an evening unit; 0.9% of people live more than 30 mi from any unit vs 17.3% from an evening unit (57 million people). Nonmetro median: 8.2 vs 42.1 mi.
- Change, Oct 2020 to Oct 2026 (units matched on CCN): 1,277 evening units became 1,131; 163 dropped the shift, 104 closed or stopped in-center HD, 98 added one, and 23 of 516 new units opened with one. By certification year (current units), the share with a late shift is 22.6% before 2000, 18.1% for 2000-09, 14.6% for 2010-14, 8.1% for 2015-19 and 4.3% for 2020 on, so newer units have not caught up as they fill.
- Regional pattern: ESRD Network 6 (GA, NC, SC) 5.4% of units; Network 16 (WA, OR, ID, MT, AK) 46.9%. Part of the state gap may be regional reporting practice; not tested.

## Sources

- CMS Provider Data Catalog, [Dialysis Facility - Listing by Facility](https://data.cms.gov/provider-data/dataset/23ew-n7w9) (23ew-n7w9). The current CSV URL is read from the dataset's metastore record each build. "Late Shift" = "a shift starting at 5:00 P.M. or later" (CMS data dictionary).
- CMS [archived snapshots](https://data.cms.gov/provider-data/archived-data/dialysis-facilities): `https://data.cms.gov/provider-data/sites/default/files/dataset-archives/theme/dialysis-facilities/dialysis-facilities_<date>.zip` for 2020-10-31, 2023-04-26, 2024-04-24, 2025-04-23, 2026-04-22. The 2021-04-12 and 2022-04-27 zips contain a byte-identical copy of the 2020 facility file, so they are skipped. The 2020 file codes yes/no as 1/0.
- Census 2020 tract centers of population; USDA 2023 Rural-Urban Continuum Codes (metro = 1-3); Census batch geocoder with ZIP-centroid fallback (via `_viz/vizlib.py`).
- "What could change this" section (added 2026-11-12, before About the data): the Late Shift field is yes/no with no evening-chair or new-patient field in the [CMS data dictionary](https://data.cms.gov/provider-data/sites/default/files/data_dictionaries/dialysis/DF_Data_Dictionary.pdf), so CMS could ask for both; Washington's certificate-of-need point for an after-5 pm shift since 2007 ([WSR 06-24-050](https://lawfilesext.leg.wa.gov/Law/WSR/2006/24/06-24-050.htm), now [WAC 246-310-827](https://app.leg.wa.gov/WAC/default.aspx?cite=246-310-827)), with no causal claim.
- Context cited on the page: Perez et al., [CJASN 2025](https://doi.org/10.2215/CJN.0000000819) (evening shift associated with a 6% higher relative employment rate, ages 18-54, 2016-2019; median facility employment 20%); Crouch et al., [Am J Nephrol 2024](https://doi.org/10.1159/000537763) (16.0% of facilities offered late-shift services in 2020 CMS data; this build's 2020 snapshot gives 16.6% of all facilities); [Medicare.gov ESRD page](https://www.medicare.gov/basics/end-stage-renal-disease) (30-month coordination period).

## Method notes

- Universe: units with "Offers in-center hemodialysis" = Yes. Territories (PR, GU, VI, AS, MP) are kept separate on the state chart; chain figures use the 50 states and DC.
- Patient weight: the column `Number of adult HD patients with KT/V data`. Do not use the "Adult HD Kt/V data availability code" column; it is a footnote code and silently breaks small states such as HI and DE.
- Chains: CMS "Chain Organization", grouped as DaVita, Fresenius (Fresenius Medical Care), US Renal Care, DCI, American Renal Associates, Independent, and Other. A chain-state row is shown with at least 20 units.
- Variance explained: eta squared and omega squared of the unit-level late-shift indicator grouped by state, by ESRD Network, by the page's chain groups, and by the raw Chain Organization name.
- Certification year: parsed from "Certification Date" (MM/DD/YYYY) in the current file; `by_certification_year` in `summary.json` also gives median patients and stations per band.
- Distance: great-circle nearest neighbour (scipy cKDTree on unit vectors) from each populated tract's population center (lower 48 + DC) to every placed unit and to units with a late shift. `dist_cdf.csv` gives the share of population beyond each whole mile 0-100.
- Churn: 2020-10-31 vs current, in-center units matched on CCN. "Closed" = an evening unit in 2020 whose CCN is not an in-center unit now (one of the 104 is still listed but no longer offers in-center HD). Relocation under a new CCN shows as a closure plus an opening.

## Output (`data/`, about 160 KB)

`summary.json` (every headline number on the page), `states.csv`, `chains.csv`, `chain_states.csv` (chain x state, at least 10 units; `shown` = at least 20), `dist_cdf.csv`, `trend.csv`, `churn.json`, `facilities.csv` (lat, lon, late flag; lower 48 + DC, rounded to 3 decimals).

## Rebuild

`python3 dialysis-after-five/scripts/build_data.py` (needs numpy and scipy; e.g. `uv run --with numpy --with scipy python dialysis-after-five/scripts/build_data.py`). Downloads are cached in `_viz/cache/dialysis-after-five/`; geocodes in `_viz/cache/dialysis_after_five_geocode.json`, seeded from the Dialysis Time Tax cache so only new units are sent to the geocoder.

## Caveats

Late Shift is a self-reported yes/no: no chair count, could be full or closed to new patients, and does not separate a 5 pm shift from nocturnal dialysis. Kt/V patient counts cover a reporting window, not a point-in-time census. Residential distance is not a patient's trip, and the nearest evening unit may be full or out of network. The 30-month point applies only to people with employer or union group coverage. No race breakdown is shown, since one built from the general population would not describe dialysis patients.
