# Noisy ruler, real differences

What Medicare's Hospital Readmissions Reduction Program (HRRP) penalties can and can't see, on fiscal 2026 data (discharges July 2021 to June 2024):

1. **Lineup.** One panel of real ERRs hidden among eight chance-only panels, per measure. Readers pick the real one.
2. **Find your hospital.** CMS's verdict for each measure, the ERR with a 90% range for the true ratio, reliability n/(n+k), and the probability that the true ratio is above the peer-group median.
3. **Persistence.** FY2023 vs FY2026 ERRs (non-overlapping windows; FY2023 covers July 2018 to November 2019 and July 2020 to June 2021, because CMS excluded December 2019 to June 2020 discharges), against the correlation that measurement noise alone would allow if no hospital changed.
4. **Design artifact.** Share penalized by number of countable measures.

**Live:** https://usnish.github.io/readmission-noise/ (a hospital can be linked directly as `#<CCN>`).

## Sources (all public, no login)

- CMS FY2026 HRRP supplemental file (final rule): `FR FY 2026.txt`
- CMS FY2023 HRRP supplemental file: `FY2023_FR_Supplemental_File FR FY 2023.txt` (discharges July 1, 2018 to December 1, 2019 and July 1, 2020 to June 30, 2021; pneumonia suppressed that year)
- CMS Provider Data Catalog dataset `9n3s-kdb3` (FY2026, hospital level), read through the datastore API, because the static CSV returns 403 to scripts
- CMS FY2027 HRRP supplemental file, used only for context and for each hospital's FY2027 verdict. Its window (July 2023 to June 2025) overlaps FY2026's, it adds Medicare Advantage stays, and hospital-level predicted and expected rates for it are not yet published.

## Method

- **Shrinkage emulation.** predicted − expected = n/(n+k) × (observed/n − expected), with one k per measure, fitted to CMS's published predicted and expected rates (R² 0.994–0.999). k is bootstrapped over hospitals (400 resamples). As a check, inverting the fit for hospitals with suppressed counts (<11 readmissions) recovers an implied count of 0–10 for 98.5–99.6% of them, depending on the measure.
- **True-ratio spread** implied by the same model: τ² = (1 − E)/(E·k).
- **Chance-only panels.** O ~ Binomial(n, E) for every hospital, shrunk with k, then converted to an ERR. Seed fixed.
- **Probability above the peer median.** Normal posterior with mean = published ERR and variance = τ²(1 − reliability). Calibration is checked by simulating hospitals that follow the model; the largest gap between stated and observed probability in any band is under 2 points.
- **Noise-only ceiling.** True ratios are held fixed across both windows, with each window's real n and the same k (300 simulations). FY2026 expected rates and k are applied to FY2023. That matches FY2023's published ERR spread for HF, AMI, COPD and CABG, but not for hip/knee, which is flagged on the page. As a sensitivity check the build also fits a separate k for FY2023 that matches its published ERR spread and reruns the ceiling (`ceiling_fy23_k` in summary.json): the ceiling moves by under 0.01 for HF, AMI, COPD and CABG, and hip/knee's falls from 0.48 to 0.44, still well above the observed 0.21.

## Rebuild

```
uv run --with numpy --with scipy python3 readmission-noise/scripts/build_data.py
```

Raw downloads are cached in `_viz/cache/` (git-ignored). The script asserts its headline numbers, including 2,945 hospitals, 78.2% penalized, a 0.30% median cut, 15 hospitals at the 3% cap, the fitted k values, the real-to-chance SD ratios, the cross-window correlations and the simulated ceilings. It writes `data/hospitals.json`, `data/lineup.json` and `data/summary.json` (about 1.3 MB in total).

## Caveats

This is an emulation of CMS's hierarchical logistic model, not the model itself. The chance-only panels apply today's shrinkage to pure noise, so they show the noise floor of published ERRs, not what CMS would publish in a world of identical hospitals. Both windows include COVID-era exclusions. ERR is a hospital-level ratio, not a patient's risk. The page lists further caveats and the prior work (Thompson 2016, Shen/Wadhera/Yeh 2021, Wilcock 2021, Joshi 2019).

Conflict of interest: the author is Medical Director of Aviary Health, a virtual cardiac and pulmonary rehab provider whose value to health systems includes reducing readmissions.
