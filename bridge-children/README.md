# Old enough to count, too young to interpret

How many US children aged 5-17 are fluent in English while every adult at home has limited English ("bridge children"), how old they are, who depends on them, and why more than half of them live in homes the Census "limited English speaking household" measure does not class as limited-English (a fluent 14-17-year-old is there). Federal health-care civil-rights rules (45 CFR 92.201(e)(3)) bar covered entities from relying on a minor child to interpret, except briefly in an emergency.

**Live:** https://usnish.xyz/bridge-children/

The "What could change this" section (before "About the data") leads with states paying for interpreters through Medicaid: 45 CFR 92.201 requires a free qualified interpreter and bars relying on a child, but states are not required to pay providers for language services, the federal match is 75% for children on Medicaid or CHIP and their family members (50% otherwise; [Medicaid.gov](https://www.medicaid.gov/medicaid/financial-management/medicaid-administrative-claiming/translation-and-interpretation-services)), and NHeLP's [March 2024 review](https://healthlaw.org/resource/medicaid-and-chip-reimbursement-models-for-language-services-2024-update/) found 18 states (including DC) that pay providers or use managed-care contracts (the "18" is typed in; update it if NHeLP updates). The adults-only companion to the Census table is now the second, shorter paragraph. All four numbers are filled from `data/summary.json` (`medicaid_share`, `dependent_adults_medicaid`, `missed_share`, `missed_by_census`) and follow the definition toggle. Rewritten 2026-11-12; reasoning in `_viz/policy/bridge-children.md`.

## Findings (ACS 2020-2024 5-year PUMS)

- 2,598,432 bridge children (SE 16,997) under the standard definition (every adult speaks English less than "very well"); 975,093 (SE 11,215) under the strict one ("not well" or "not at all").
- 70.7% of homes where every adult has limited English and a child aged 5-17 lives have one. The rate is similar across the most common languages.
- 66% are 13 or younger. The count rises from 120,000 at age 5 to about 235,000 at ages 13-14, then levels off.
- 54.5% (1,416,732 children in about 727,000 homes) live in homes the Census measure classes as *not* limited-English, because a 14-17-year-old in the home is fluent.
- 3.05 million adults live in these homes: 839,000 on Medicaid and 164,000 aged 65 or older. 32% of the children are below the poverty line and 66% are on Medicaid or CHIP.

## Sources

- U.S. Census Bureau, ACS 2020-2024 5-year PUMS, [person](https://www2.census.gov/programs-surveys/acs/data/pums/2024/5-Year/csv_pus.zip) and [housing](https://www2.census.gov/programs-surveys/acs/data/pums/2024/5-Year/csv_hus.zip) files; [data dictionary](https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2020-2024.csv).
- Checks: the ACS 2024 1-year PUMS (person + housing) and the ACS 2019 1-year PUMS (person).
- Census definition of a limited English speaking household: [2024 ACS Subject Definitions](https://www2.census.gov/programs-surveys/acs/tech_docs/subject_definitions/2024_ACSSubjectDefinitions.pdf), p. 55.
- [45 CFR 92.201](https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-A/part-92/subpart-C/section-92.201) (eCFR, current as of 2026-11-06; this version effective 2024-07-05). The minor-child bar has been in the Section 1557 rule since 2016 (92.201(e)(3) in 2016, 92.101(b)(4)(iii) under the 2020 rule, 92.201(e)(3) again since July 5, 2024).
- Prior work: Dietrich & Bauman, [SEHSD-WP2019-16 poster](https://www.census.gov/content/dam/Census/library/working-papers/2019/demo/sehsd-wp2019-16-poster.pdf) (PAA 2019, 2017 ACS); KFF, [Overview of Health Coverage and Care for Individuals with Limited English Proficiency](https://www.kff.org/racial-equity-and-health-policy/overview-of-health-coverage-and-care-for-individuals-with-limited-english-proficiency/) (September 2026); KIDS COUNT, [children in linguistically isolated households](https://datacenter.aecf.org/data/tables/129-children-living-in-linguistically-isolated-households-by-family-nativity).
- Language brokering: Shen et al., *Am Psychol* 2022;77(8):921-939, [doi:10.1037/amp0001035](https://doi.org/10.1037/amp0001035) (PubMed 36190758).

## Method

- **Fluent:** LANX = 2 (only English) or ENG = 1 ("very well"). **Limited English adult (standard):** age 18+, LANX = 1 and ENG in 2-4. **Strict:** ENG in 3-4.
- **Qualifying home:** a housing unit (group quarters dropped, RELSHIPP 37/38) with at least one adult, where every adult has limited English. **Bridge child:** age 5-17, fluent, in a qualifying home.
- **Census flag:** a home is a limited English speaking household when no one aged 14+ is fluent. In a qualifying home, that fails exactly when a 14-17-year-old is fluent. The recomputed flag matches the Bureau's LNGI variable in all 234,742 qualifying sample homes.
- **Weights:** person counts use PWGTP, and household counts and rates use WGTP (joined from the housing file on SERIALNO). SEs use the 80 replicate weights: SE = sqrt(4/80 × Σ(rep − est)²). The page shows 90% MOEs (1.645 × SE).
- **Household language:** the householder's (reference person, RELSHIPP 20) LANP, or the first adult's if the householder is under 18. Chinese, Mandarin, Min Nan and Cantonese are grouped as "Chinese", and Tagalog and Filipino as "Tagalog/Filipino". Language rows require at least 100 sample homes with a child aged 5-17. Languages are compared only on the rate among homes that have a school-age child, never on the share of all limited-English homes, because many Korean and Russian limited-English homes have no school-age children.
- **States:** cells are blank when SE/estimate > 0.30.
- **Poster check:** on the 2019 1-year file, 19.7% of fluent children aged 5-17 in homes with an adult who speaks another language live where every adult speaks English less than "very well". The poster reports 20.7% for 2017. The 2024 figure is 16.0%.

## Caveats

- One respondent reports English ability for everyone in the home. For a young child, "very well" means fluent for their age, not able to interpret.
- Being the only fluent speaker does not show that a child interprets. Relatives and others outside the home are not counted.
- 45% of the adults in these homes speak English "well", so the strict count is shown too.
- The Census 14+ rule is a deliberate statistical convention, not an error. The page sets it beside the health-care rule rather than calling it a mistake.
- There is no per-interpreter ratio (OCCP × LANP gives the interpreter's home language, not their working language). A figure of 11 million child language brokers is widely repeated but has no traceable source; it is not comparable to the count here.

## Rebuild

```
python3 bridge-children/scripts/build_data.py
# or, without a local numpy:
uv run --with numpy --with scipy python3 bridge-children/scripts/build_data.py
```

The first run downloads about 4.1 GB of zipped PUMS into `_viz/cache/bridge/`. With the files cached, a build takes about 4 minutes on 12 cores. Output (under 15 KB): `data/summary.json`, `data/ages.csv`, `data/lang.csv`, `data/deps.json`, `data/states.csv`.
