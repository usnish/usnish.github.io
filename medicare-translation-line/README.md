# Where a Medicare plan has to put your denial letter in your language

Medicare Advantage and Part D plans must translate required materials (Evidence of Coverage, Annual Notice of Change, denial and appeal notices, formulary) only into a language that is "the primary language of at least 5 percent of the individuals in a plan benefit package (PBP) service area" (42 CFR 422.2267(a)(2), 423.2267(a)(2)). This page measures, language by language, how many people with limited English that rule reaches, using every 2027 plan's real service area.

## Build

```
uv run --with numpy --with scipy python3 medicare-translation-line/scripts/build_data.py
```

(Any Python 3 with numpy and scipy works; they are needed only because the shared `_viz/vizlib.py` imports them.) Downloads are cached in `_viz/cache/`:

- ACS 2020-2024 5-year table-based summary files `acsdt5y2024-c16001.dat`, `-b16001.dat`, `-b16004.dat`, plus `Geos20245YR.txt` and `ACS20245YR_Table_Shells.txt` (the script checks the C16001 line labels against the shells).
- CMS PBP benefits files for 2026 and 2027 (PlanArea, PlanRegionArea, Section A) and the September 2026 CPSC enrollment file, through `_viz/malib.py`.
- 2020 census tract centers, to rebuild Connecticut's old counties from tracts.

## Outputs (`data/`)

- `coverage.csv`: language x basis (lep = CMS's published limited-English method; all = everyone who speaks it) x unit (plans = real 2027 service areas; enrolled = 2026 plans weighted by September 2026 enrollment; county = each county of 10k+ as its own plan, with MOE band; state).
- `counties.csv`: every county of 10k+ where Chinese, Vietnamese, Korean, Tagalog or Arabic is 3%+ on either basis, with 90% MOEs and the 2027 plans open to anyone there.
- `plans.csv`, `plan_list.csv`: plans and contracts that must translate each language (non-Spanish list in full).
- `languages.csv`: B16001 detailed languages at state and PUMA level, plus an approximate top-15-in-state share.
- `age.csv`: B16004 language groups, share of all ages vs 65+, for the six counties with the most Asian/Pacific Island-language speakers 65+ with limited English.
- `summary.json`: headline numbers and checks. `policy.json`: dated policy timeline (written by the script).
- `summary.json` `alt_thresholds`: what-if triggers for the "What could change this" section, CMS's limited-English method, real 2027 plans anyone can join (3,526), for Chinese, Vietnamese, Korean, Tagalog and Arabic. `current` = the 5% service-area rule; `county` = 5% across the service area, or any county the plan serves with 10,000+ speakers with limited English (modeled on Voting Rights Act section 203, which counts voting-age citizens and also has a county 5% prong not used here); `n1000` = 5%, or 1,000+ speakers with limited English across the whole service area (Justice in Aging's "5% or 1,000 people, whichever is lower" counts everyone who speaks the language, so theirs would reach at least as many plans). Each gives open plans that must translate any of the five (`plans_any`) and each language (`by_language.plans`), limited-English speakers living in a county where at least one open plan must translate (`lep_reached`, `pct`; residents, not enrollees, so an upper bound), and open plans that must translate Vietnamese in Orange County, CA (06059) and Chinese in San Francisco (06075).

## Findings (build of 2026-11-12)

- CMS method, real 2027 plans: Spanish 85.5%, Chinese 29.1%, Vietnamese/Korean/Tagalog/Arabic 0% of limited-English speakers live in a county where at least one plan open to anyone must translate.
- Most generous reading: Vietnamese 20.8%, Tagalog 4.5%, Korean and Arabic 0%.
- Weighted by where people actually enroll: Chinese 3.1% (CMS method).
- Navajo-area counties (McKinley NM, Apache AZ, San Juan NM and UT, Navajo AZ) cross 5% for "other languages" on their own, but no plan sold there must translate.
- Alternative triggers (Chinese, Vietnamese, Korean, Tagalog, Arabic combined): now 24 open plans, 529,132 of 4,300,177 (12.3%); county 10,000 test 950 plans, 3,364,948 (78.3%), Orange County Vietnamese 72 of 72 (now 0), San Francisco Chinese 35 of 35 (now 18); 1,000 floor 2,965 of 3,526 plans.
- Validation: the limited-English method finds 17 non-PACE contracts for Chinese and 16 for "other Asian" in 2027, close to CMS's own 2023 count (16 and 19, 88 FR 22227); the all-speakers method would add Vietnamese and French/Haitian contracts CMS never reported.

## Caveats

County shares are 5-year estimates for everyone 5+, not Medicare enrollees. CMS's current exact method is in non-public HPMS technical notes. The rule covers written translation only; interpreters, translation on request and OCR's 15-language notice still apply. Recheck for a CY2028 proposed rule before relaunching.
