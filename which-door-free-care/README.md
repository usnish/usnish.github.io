# Which door? Free care at nonprofit ERs, county by county

Every nonprofit hospital sets its own income cutoff for free care. This page compares the nonprofit hospitals with a 24-hour ER inside each U.S. county and counts the uninsured residents under 65 whose income falls between the county's lowest and highest cutoff: free care at one door, a bill at another. It opens with a guess-first chart (drag two handles to guess a county's lowest and highest cutoff, then see the hospitals).

**Live:** https://usnish.xyz/which-door-free-care/

## Finding (built 2026-11-12)

- 266 counties have nonprofit ERs with different free-care cutoffs, after state free-care laws. They hold 9.7 million uninsured people under 65.
- 1.2 to 2.3 million (1.17-2.25) of those people have incomes between their county's lowest and highest cutoff.
- In those counties, 41% of uninsured residents would qualify at the stingiest nonprofit ER and 64% at the most generous.
- Sensitivities: before state laws, 1.4-2.5 million in 276 counties; leaving out people under 138% FPL in expansion states, 1.0-2.1 million; without Los Angeles County, 0.7-1.8 million; CMS-matched hospitals only, 1.1-2.2 million.

Prior work (credited on the page) shows that the cutoffs vary and don't track need: KFF 2022, Messac et al. (Health Affairs 2024), Santos et al. (Health Affairs 2026), Wong et al. (HSR 2026) and Lown Institute data. The Lown Institute has also compared neighboring hospitals in Boston, Dallas, Pittsburgh and Waco ("Free care: Neighboring hospitals may have wildly different policies"). None does a nationwide county-by-county comparison or counts the people affected. That is what this page adds.

## Sources

- **IRS Form 990 Schedule H**, Part V Section B line 13 ("FPG family income limit for eligibility for free care"), from the IRS TEOS e-file XML bulk releases of 2024, 2025 and 2026 (https://www.irs.gov/charities-non-profits/form-990-series-downloads). About 11 GB of zips are downloaded into `_viz/cache/scout_afford/irs/`. Each filer's latest return is used (mostly tax year 2024).
- **CMS Hospital General Information** (`_viz/cache/Hospital_General_Information.csv`, https://data.cms.gov/provider-data/dataset/xubh-q36u). Used for hospital type (acute or critical access versus children's or psychiatric) when a facility matches by ZIP code, name and street number.
- **Census geocoder** (geographies, current vintage) for each hospital's county. Fallbacks, in order: the Census 2020 ZCTA-to-county relationship file, CMS's county, and the Census Connecticut town-to-planning-region crosswalk.
- **ACS 2020–2024 5-year**, table-based summary file: C27016 (uninsured by ratio of income to poverty, by age, county) and B17024 (finer poverty-ratio bins, used only to split partial bins).
- **USDA ERS 2023 Rural-Urban Continuum Codes**, used for Illinois's rural line.
- **HHS 2026 poverty guidelines**, used for dollar labels ($27,320 for a family of three).
- **State free-care laws**: the `FLOORS` table in `scripts/build_data.py` cites each statute or rule. Applied as free-care floors: NY, WA (two tiers, from the DOH tier list), IL (200%, or 125% at rural and critical access hospitals), OR, MD, NJ, RI, ME (200% since July 2026), MA (Health Safety Net, 150%) and OH (HCAP, 100%). Recorded but not applied, because they are discount or price-cap laws: CA, CO, CT and NV.

## Method

1. `scripts/irs_scan.py` reads every return in the release zips. The largest zips use Deflate64, which Python's zipfile can't read, so those members are repacked into small plain zips and extracted with Info-ZIP `unzip`. Results are cached per zip in `_viz/cache/which_door/schedh/`.
2. Section B policy blocks are linked to Section A facilities in this order: reporting-group code, then facility name, then line number. If every block on a return gives the same line, the line applies to all of its facilities, and single-policy returns cover all their facilities. 2 facilities could not be linked and are logged in `_viz/cache/which_door/build_log.txt`.
3. A facility is kept if it has a 24-hour ER on Schedule H and is acute care or critical access. CMS's type decides when the facility matches CMS's file. Otherwise the Schedule H "general medical & surgical" box decides, with specialty hospitals dropped by name. Many large general hospitals tick the Schedule H "children's hospital" box, so that box is used only when there is no CMS match.
   - A blank Schedule H ER box is overridden when CMS lists the same hospital (name Jaccard >= 0.5 or identical name, not a clinic-type name, one facility per CCN, and no ER-ticked facility already holds that CCN) as acute or critical access with emergency services: 45 hospitals. Brookdale (Brooklyn) is confirmed by hand (`ER_CONFIRMED`).
   - `CAMPUSES` adds 8 campuses of multi-campus licenses that Schedule H lists only at the main campus (NYU Langone Brooklyn and Long Island; NYP Brooklyn Methodist, Columbia, Allen, Lower Manhattan; Mount Sinai Queens; Interfaith under Brookdale's license), with sources.
   - Dropped: `KNOWN_CLOSED` (Wellstar AMC) and `SUPERSEDED` (St. Margaret's Spring Valley, Wenatchee Valley Hospital, Tulane hospitals sold to LCMC); returns from TY2022 or earlier that don't match CMS's current file; older returns at the same address as a newer filer; and `JV_FILERS` (Methodist Healthcare Ministries' hospitals, run by an HCA-majority partnership).
   - General ER hospitals with no usable line (0 or blank, e.g. Emory, BIDMC, Regional One) are listed per county in `counties.csv` (`doors_noline`, `noline_names`) and on the page, not compared.
4. Effective line = the higher of the hospital's line and the state free-care floor. Washington tiers come from an explicit name list copied from DOH 346-149 (`WA_TIER1`). `FAP_CHECKS` records spot checks of posted policies for the 100% doors that drive the most people: PIH Downey/Whittier, Eisenhower and Temple confirm 100%; Boulder City Hospital (NV) posts 200%, which is used.
5. For each county, the people between doors are the uninsured under 65 with income above the lowest effective line and at or below the highest. The low figure counts only C27016 bins that lie wholly in that range. The high figure splits partial bins in proportion to the county's B17024 population under 60, straight-line within the fine bins. The top bin is treated as running to 1,000% of poverty.

Robustness numbers are in `summary.json`: before floors (`*_raw`), and using only facilities that match CMS's list (`*_cms`). Sanity checks: the median line is 200% and 48% of facilities sit at exactly 200%, in line with Messac 2024. The total of 27.0 million uninsured under 65 is in line with ACS national totals for these years.

## Output

- `data/facilities.csv`: one row per general nonprofit ER, with the reported line, state floor, effective line, asset and residency tests, CMS CCN and link method.
- `data/counties.csv`: uninsured under 65 by income bin, the min and max effective line, people between doors (low and high), the number eligible at the stingiest and most generous door, and the same before floors.
- `data/floors.csv`: state laws with citations.
- `data/summary.json`: every number quoted on the page.

Run `python3 which-door-free-care/scripts/build_data.py`. It uses only the Python standard library, plus `curl` and `unzip` on the PATH. The first run downloads the IRS zips; after that it takes about a minute.

## Caveats

- Public hospitals and for-profit hospitals file no Schedule H, so "stingiest" and "most generous" mean among nonprofits only.
- Eligibility here is income only. It ignores asset and residency tests and presumptive eligibility. Many uninsured people under 138% of poverty in expansion states qualify for Medicaid.
- ACS uses Census poverty thresholds and family income; hospital policies use HHS guidelines and household income.
- A county is an imperfect market.
- The lines are as reported for tax years 2023–2024 and may predate later policy changes.
- Multi-campus licenses outside NYC and Long Island may still hide campuses; missing doors can only widen a county's range.
- `build_log.txt` lists stale returns that set a county's min or max (6, all TY2022-2023 hospitals still in CMS's file).
