# Charity care at nonprofit hospitals

How much free and discounted care U.S. nonprofit acute care and critical access hospitals report, by whether their state expanded Medicaid, how it changed from one cost-report year to the next, and a rough comparison with each hospital's federal income tax exemption.

**Live:** https://usnish.xyz/hospital-charity-care/

## Sources

- **CMS Hospital Provider Cost Report (HCRIS)**, data.cms.gov. Main year: the 2024 file (`CostReport_2024_Final.csv`, catalog modified 2026-10-05), which holds cost reports for hospital fiscal years that *began* between October 2023 and September 2024 (they end between December 2023 and October 2025). Prior year: the 2023 file (years beginning October 2022 to September 2023), used only for the same-hospital comparison. Charity care is "Cost of Charity Care" (Worksheet S-10, at cost).
- **KFF, Status of State Action on the Medicaid Expansion Decision** (state table with implementation dates, as of November 2026), and **KFF, Medicaid income eligibility limits for adults** (as of January 2026; used for the Wisconsin and Georgia notes). Both are parsed by the build script from the KFF pages.
- **CDC/ATSDR Social Vulnerability Index 2022** (ACS 2018–2022): county uninsured rate and share of residents below 150% of the poverty line, rolled up from tracts to 2020 counties.
- **Census geocoder** for hospital addresses (ZIP-area center when an address doesn't match). Seven hospitals with post-office-box-only ZIPs are placed by the county named in CMS's Hospital General Information file.

## Method

- Nonprofit (church or other voluntary) short-term acute care and critical access hospitals in the 50 states and DC; each hospital's latest report in the file. Hospitals with net income above 50% of total costs are left out (usually one-time items or reporting differences).
- **Expansion status is matched to each report's dates.** A hospital's report counts as "expanded" only if its state's expansion took effect on or before the day its fiscal year began, and "not expanded" if the state hadn't expanded by the day it ended. A state is grouped as expanded or not expanded only if all of its hospitals fall in that group; otherwise it is "expanded during these years." In the 2024 file that is North Carolina (expanded 2023-12-01), shown separately. South Dakota (2023-07-01) is expanded for every 2024-file report but falls inside the 2023 file, so it and North Carolina are left out of the expansion split of the year-over-year change.
- **Blank charity care is missing, not $0.** HCRIS public files store no zeros (0 of 6,109 rows in the 2024 file has a literal 0 for "Cost of Charity Care"), so a blank can mean $0 or a line never filled in. The 87 hospitals with a blank charity care line (42 of them with the whole S-10 uncompensated care block blank) stay in the hospital list and the scatter's left band, labeled "Blank", but are left out of every median, aggregate share, the tax comparison and the year-over-year pairs (98 pairs dropped for a blank in either year). Counts are in `summary.json` (`charity_not_reported*`, `change.pairs_not_reported`).
- "Typical hospital" = median of charity care / total costs across hospitals that reported charity care. The state chart places each state at its median hospital.
- County groups are quarters of hospitals by county uninsured rate or poverty rate (cutoffs from hospitals that reported charity care), with medians shown separately for expansion and non-expansion states. Spearman correlations are in `summary.json` (expansion states, poverty vs charity share: rho 0.00, p 0.9; uninsured vs charity share: rho 0.22).
- Year-over-year change uses hospitals present in both files whose reports cover a full year (350–380 days) in both.
- Tax exemption estimate: 21% of positive net income. A floor that leaves out state and local property and sales tax exemptions, tax-exempt bonds and deductible donations; cost-report net income includes investment gains.
- Charity care is one part of community benefit; Medicaid shortfalls, education, research and community programs reported on IRS Schedule H are not included. Government-owned hospitals are not included.

## Output

`data/hospitals.csv` (one row per hospital), `data/states.csv` (state medians and expansion dates), `data/counties.csv`, `data/summary.json` (every number quoted on the page).

## What changed (November 2026)

- Moved from the 2023 file to the 2024 file (fiscal years beginning October 2023 to September 2024) and added the same-hospital comparison with the 2023 file.
- Reframed the page around Medicaid expansion (headline, stats, state strip chart, county uninsured and poverty quarters split by expansion status). The tax-exemption scatter moved lower, its dots are colored by expansion status, and its headline now says what the share means: of hospitals with positive net income, the share whose estimated federal tax break exceeded their charity care.
- Fixed year wording: these are fiscal years *beginning* in the stated period, not calendar years.
- Hospitals that the geocoder couldn't place are now kept (placed by CMS street address or county name) instead of dropped.
- Reviewer leads checked: the 2023-file split (median 4.4% vs 1.3%; non-expansion states 21% of hospitals and 39% of charity dollars) holds for that file; on the 2024 file it is 4.2% vs 1.5%, 21% and 37%. The same-hospital rise is +22% ($16.5B to $20.3B) as claimed, but the expansion-state rise is +32% (not +28%) once states that expanded during the two years are left out and only full-year reports are compared; non-expansion states +13%. In expansion states, charity care is flat across county poverty quarters at about 1.4–1.6% of costs in the 2024 file (the reviewer quoted 1.2–1.3%; not rechecked on the older file).
- Second review (November 2026): blank charity care no longer counted as $0 (see Method). Headline medians moved from 4.2% vs 1.5% to 4.4% vs 1.6%; tax share from 59.1% of 1,970 to 58.0% of 1,917 (still about 6 in 10); year-over-year +22.4% all, +30.9% expansion, +15.2% non-expansion. Lede and tax wording now match the law (income tax exemption; community benefit standard sets no charity care minimum). Added the outside-the-South check (non-expansion 1.3% vs expansion 1.6%; Kansas 1.9%, Wyoming 2.4%) and the unwinding check (960 hospitals whose earlier year began April 2023 or later: +24%). New link-preview image from the state strip chart.

Rebuild: `python3 hospital-charity-care/scripts/build_data.py` (needs numpy and scipy, e.g. `uv run --no-project --with numpy --with scipy python3 hospital-charity-care/scripts/build_data.py`).
