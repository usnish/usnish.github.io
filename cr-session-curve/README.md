# Same curve, two worlds

What the 36-session cardiac rehab curve can and can't tell you. Hammill et al. (Circulation 2010) found that Medicare patients who attended 36 cardiac rehab sessions had lower 4-year mortality than those who attended 24, 12 or 1 (adjusted HR 0.86 / 0.78 / 0.53). This page simulates two worlds, one where sessions do nothing and one with a modest benefit that stops at 12 sessions, runs Hammill's analysis on each, and shows that both can draw Hammill's curve. It sets Hammill's 0.53 beside the randomized evidence (Cochrane 2021) and the placebo-adherer literature.

**Live:** https://usnish.github.io/cr-session-curve/

## What's here

- `index.html`: the page (d3 v7 from `../assets/viz/`).
- `data/published.json`: every published number used, with study, contrast, metric (HR/RR/OR/RD, adjusted or crude), follow-up window, DOI and where in the paper it appears. Includes the 4-year mortality read off Hammill's Figure 2.
- `data/grid.json`: simulated hazard-ratio curves (36 sessions vs k, k = 1..36; 10th/50th/90th percentile over 20 synthetic cohorts) for 140 settings, plus 28 sensitivity settings for the 4-year mortality assumption.
- `data/calibration.json`: fitted stopping parameters and achieved calibration targets for each program-reason share.
- `data/summary.json`: headline numbers quoted on the page.
- `scripts/build_data.py`: writes `published.json` and checks every quoted string against the source text (PubMed abstracts, the PMC full text of Hammill, the Cochrane PDF, the CMS decision memo); writes `summary.json` once the grid exists. Stdlib only.
- `scripts/sim.py`: the simulation and estimator (numpy, scipy).

## Rebuild

```
python3 cr-session-curve/scripts/build_data.py
uv run --with numpy --with scipy python3 cr-session-curve/scripts/sim.py      # about 6 minutes on 12 cores
python3 cr-session-curve/scripts/build_data.py
```

Seeds are fixed, so a rerun reproduces the shipped files. Downloads are cached in `_viz/cache/` (not published). `build_data.py` needs `pdftotext` (poppler) to check the Cochrane numbers; without it, that check is skipped with a message.

## Method in brief

- 30,000 synthetic Medicare rehab starters per cohort, 20 cohorts per setting, weekly steps for 4 years. A hidden trait Z ~ N(0,1) raises the hazards of stopping rehab, hospitalization and death; the analysis sees only a measured part (correlation 0.5 with Z).
- Attendance: up to 3 sessions offered a week for 36 weeks (each attended with probability 0.8), capped at 36. Stopping comes from a trait-linked hazard (separate rates by session range; weaker trait link from session 12), a program end point between 24 and 35 sessions for a share of people regardless of health, and hospitalization (front-loaded, pauses attendance 3 weeks; some resume). Optional pre-death decline stops attendance 8 weeks before death.
- Calibrated, for each program-reason share, to Hammill's session distribution (median 25, IQR 13-34, 18% at 36, 13% under 6, more than 40% at 30+), 28.4% hospitalized in 36 weeks, 31% of them resuming, R² = 0.05 for measured covariates, and the spacing of 4-year death rates across the four attendance groups in Hammill's Figure 2. Death hazards are fitted in every setting to 2.0% mortality at 36 weeks and 13.9% at 4 years (read from Figure 2; ±5 points as a sensitivity check).
- World B: sessions have no effect. World A: log-HR −0.15 once 12 sessions are attended, no further gain (one assumption consistent with Cochrane, not an estimate).
- Estimator, as in Hammill: cumulative sessions as a time-dependent restricted cubic spline (knots 10/16/22/28), adjusted for the measured trait and a time-dependent hospitalization flag. Implemented as a piecewise-exponential Poisson GLM fit by IRLS on person-weeks pooled by time band, sessions, hospitalization and tenth of the measured trait (equivalent to Cox with time bands). A 6-group version replaces the spline.

## Caveats

The simulation shows what is possible, not what is: its settings are assumptions shown across a stated range, and a world with a real benefit fits Hammill's numbers as well as a world with none. Metrics on the page differ (adjusted time-dependent HR, intention-to-treat RR, crude risk ratio, risk difference, OR) and are never placed on one axis. Cochrane's cardiovascular death, MI and hospitalization results are shown next to all-cause mortality.

Conflict of interest: the author is Medical Director of Aviary Health, which provides virtual cardiac rehab and intensive cardiac rehab (72 sessions). The same critique applies to ICR dose-response claims, including Medicare analyses such as doi 10.1161/CIRCOUTCOMES.123.010131.
