# Charity care at nonprofit hospitals

Charity care reported by U.S. nonprofit acute care and critical access hospitals for 2023, plotted against a rough estimate of each hospital's federal income tax exemption (log scales).

**Live:** https://usnish.github.io/hospital-charity-care/

Sources: CMS Hospital Provider Cost Report (HCRIS) 2023, Census geocoder, CDC/ATSDR SVI 2022. Hospitals with net income above 50% of total costs are left out (usually one-time items or reporting differences). The vertical axis is a rough floor on each hospital's federal income tax exemption (21% of positive net income); hospitals without positive net income sit in a $0 band. State and local exemptions, tax-exempt bonds and donations are not included. Charity care is only one part of community benefit; Medicaid shortfalls, education, research and community programs reported on IRS Schedule H are not included.

Rebuild: `python3 hospital-charity-care/scripts/build_data.py`.
