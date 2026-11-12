# The 65th birthday that never comes: who Medicare leaves uninsured

Page: https://usnish.xyz/medicare-at-65/

Who is uninsured at 65 and older in the US, by nativity, citizenship, age at arrival, years in the US and language, from American Community Survey microdata.

"What could change this" (static text, after "Earned, or by residence"): residency test in Medicare for All bills, with the 5-year buy-in rule and HEAL Act as context; its numbers are typed in from `summary.json` (`years_rate`, `price`), so update them by hand if the data are rebuilt.

## Build

```
python3 medicare-at-65/scripts/build_data.py [workers]   # needs numpy
```

The first run downloads (or reuses from `_viz/cache/`) the ACS PUMS person files and streams them: 2022, 2023 and 2024 1-year (people 55+) and 2020-2024 5-year (people 65+). It takes about 10-20 minutes on 6 cores. Extracts are cached as `.npz` in `_viz/cache/medicare65/`, so later runs take under a minute.

## Method

- Universe: civilian noninstitutional population (drops RELSHIPP 37, institutional group quarters), the universe ACS uses for health insurance. Uninsured = HICOV 2.
- Age at arrival = AGEP - (survey year - YOEP). YOEP is the year of most recent entry.
- Weighted rates; standard errors by successive difference replication with the 80 replicate weights (var = 4/80 * sum of squared deviations). Pooled 1-year files: every weight divided by 3.
- Single-year-of-age cells with fewer than 100 records are blanked; language cells need at least 100 records. Pennsylvania German is excluded from the language chart (Amish religious opt-out from Social Security and Medicare) and reported in `summary.json`.
- Medicare premiums are CMS's 2026 figures, typed into the script as constants.

## Outputs (`data/`)

- `composition.json`: 2024 uninsured 65+ count, shares by nativity, citizenship, arrival at 55+, limited English; rates by citizenship.
- `curves.csv`: uninsured % by single year of age (55-85) for US-born, three age-at-arrival groups, limited-English citizens and noncitizens, and English-only speakers (pooled 2022-24), with 95% CIs.
- `years_in_us.csv`: immigrants 65+, uninsured % by years since arrival (pooled 2022-24).
- `lang65.csv`: 65+ with limited English, uninsured % by detailed language (2020-24 5-year), for all, citizens and noncitizens.
- `price.json`: 2026 buy-in premiums and a profile of uninsured seniors who arrived less than 10 years ago.
- `summary.json`: headline numbers used in the page text.
