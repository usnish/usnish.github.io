# Charity care at nonprofit hospitals

Charity care reported by U.S. nonprofit acute care and critical access hospitals for 2023, mapped over county uninsured rates.

**Live:** https://usnish.github.io/hospital-charity-care/

Sources: CMS Hospital Provider Cost Report (HCRIS) 2023, Census geocoder, CDC/ATSDR SVI 2022. Hospitals with net income above 50% of total costs are left out (usually one-time items or reporting differences). Each hospital's details include a rough, partial estimate of its federal income tax exemption (21% of positive net income) for context. Charity care is only one part of community benefit; Medicaid shortfalls, education, research and community programs reported on IRS Schedule H are not included.

Rebuild: `python3 hospital-charity-care/scripts/build_data.py`.
