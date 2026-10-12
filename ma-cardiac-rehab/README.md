# What cardiac rehab costs in Medicare Advantage

What Medicare Advantage members pay for Medicare-covered cardiac rehab (36 sessions) and intensive cardiac rehab (72 sessions), by county, for 2026 and 2027, compared with traditional Medicare's 20% coinsurance, plus how many members need prior authorization.

**Live:** https://usnish.github.io/ma-cardiac-rehab/ (password-protected)

Sources: CMS Plan Benefit Package files 2026 and 2027 (section B3 cardiac and pulmonary rehab, section D out-of-pocket maximum, PlanArea), CMS monthly enrollment by contract/plan/state/county (September 2026), CMS 2027 plan crosswalk, CY2026 OPPS Addendum A (APC 5771, $131.70 per session).

Method: per-session in-network cost sharing for each plan segment (copay, or coinsurance × the APC 5771 rate), × 36 or 72 sessions, capped at the plan's in-network out-of-pocket maximum; averaged over enrolled members by county. 2027 follows each member to their crosswalk plan. Dual-eligible SNP members are left out of cost figures because Medicaid usually pays their cost sharing.

The page is published encrypted. The plaintext page and data live in `_src/` (git-ignored).

Rebuild: `python3 ma-cardiac-rehab/scripts/build_data.py`, then `python3 _viz/encrypt_page.py ma-cardiac-rehab` (asks for the password, or reads `PAGE_PASSWORD`). Needs `cryptography`.
