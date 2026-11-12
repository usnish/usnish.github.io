# One High Reading

How much a single high systolic reading falls on its own. NHANES III (1988–94) measured 15,689 U.S. adults three times at home, by a trained household interviewer, and three more times at a mobile exam centre, by a physician, about a month later. Both used mercury sphygmomanometers, and no treatment change was recorded between the visits.

The page:

1. **Predict first.** The reader draws where people with each first home reading ended up at the exam centre. Then all 15,689 people animate from the no-change line to their exam-centre average, and the weighted binned means are drawn over the guess (slope 0.73). Toggles remove the home-vs-centre offset and show subgroups.
2. **Where the drop comes from.** Stacked bars at cutoffs of 130, 140 and 160 split the fall into the setting offset, same-visit regression (home reading 1 vs home readings 2–3) and second-day regression. A toggle switches to picking people on the mean of three readings.
3. **Reverse check.** People picked high at the exam centre were lower at home than the offset predicts, so the drop is not a home/clinic artifact.
4. **After a pill.** The Law 2003 placebo-adjusted standard-dose effect stacked with the regression shown here.
5. **Today's machines.** NHANES 2021–23 oscillometric readings: reading 1 minus the mean of readings 2–3 among people whose first reading was 140 or more.
6. **Remeasure-only program.** A slider shows the apparent improvement at each enrollment cutoff.

## Build

From the repo root (numpy and scipy needed; the mini's system python has neither):

```
uv run --with numpy --with scipy python3 one-high-reading/scripts/build_data.py
```

Raw files are cached in `_viz/cache/` (git-ignored) via `_viz/vizlib.py`:

- `https://wwwn.cdc.gov/nchs/data/nhanes3/1a/adult.dat` (67 MB, fixed width; layout `adult.sas`)
- `https://wwwn.cdc.gov/nchs/data/nhanes3/1a/exam.dat` (195 MB; layout `exam.sas`)
- `https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/BPXO_L.xpt` and `DEMO_L.xpt`, read with `scripts/xpt.py` (a stdlib/numpy SAS XPORT v5 reader)

The script checks its output against the expected figures (n = 15,689; offset 3.80; 7.3 beyond the offset at 140+; slope 0.73; reverse check 9.1; and others) and stops if any differs by more than 0.15.

Outputs (about 0.7 MB in all, no survey IDs):

- `data/people.csv`: one row per person: home readings `h1`–`h3`, exam-centre readings `m1`–`m3`, MEC weight rounded to an integer, `told` (doctor ever said high BP: 1/0/blank), `meds` (now taking BP medicine: 1/0/blank; asked only of those told), age band. Rows are sorted by value.
- `data/within2023.csv`: NHANES 2021–23 adults with three readings: `sbp1`, `mean23`, weight.
- `data/summary.json`: every number quoted on the page, including Taylor-linearised 95% CIs (NHANES III strata/PSUs) for the headline figures.

## Gotchas

- Column positions are 1-based from the `.sas` layouts: HSAGEIR 18–19, HSAITMOR 21–24, SDPPSU6 43, SDPSTRA6 44–45, WTPFEX6 61–69, HAE2 1598, HAE5A 1610, HAZA8AK1/BK1/CK1 3288/3296/3304; exam file MXPAXTMR 1236–1239, PEP6G1/H1/I1 1393/1403/1413.
- Readings outside 60–290 (including 888-style missing codes) are dropped.
- The interviewer read each person a statement about their home result (average of readings 2–3), so some may have sought care before the exam. Treatment started between visits is not recorded.
- Averaging three readings at one visit trims the phantom drop by about a tenth at 140, by less at 130, and not at all at 160 (the groups picked differ). The page says so instead of claiming a constant tenth.
- `viz.css` has no dark theme. Like the other viz pages, this one renders light, and all colours come from the shared tokens.
