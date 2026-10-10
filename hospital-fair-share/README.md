# Nonprofit hospital fair share

Charity care reported by U.S. nonprofit acute care and critical access hospitals in 2023, compared with a conservative estimate of their federal tax break (21% of positive net income), over county uninsured rates.

**Live:** https://usnish.github.io/hospital-fair-share/

Sources: CMS Hospital Provider Cost Report (HCRIS) 2023, Census geocoder, CDC/ATSDR SVI 2022. Hospitals with net income above 50% of total costs are excluded as likely one-time gains or reporting errors. The estimate leaves out state, property and sales tax exemptions, so the full tax break is larger; see the Lown Institute's Fair Share Spending for an IRS-990-based estimate.

Rebuild: `python3 hospital-fair-share/scripts/build_data.py`.
