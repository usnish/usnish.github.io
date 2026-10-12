# Medicare Advantage plans ending in 2027

Where Medicare Advantage members go next year according to the CMS plan crosswalk (stays in plan, moved automatically to another plan, plan leaving their county, plan ended), by county, insurer and plan type, for 2027 and, for comparison, 2026.

**Live:** https://usnish.github.io/ma-plan-exits/

Sources: CMS Plan Crosswalk 2026 and 2027 (October 1 releases), CMS monthly enrollment by contract/plan/state/county (September 2025 and September 2026), CMS Plan Benefit Package files 2025–2027 (Section A plan details, PlanArea service areas).

Method: each plan-county enrollment cell follows its plan's crosswalk rows; a destination counts only if its next-year PlanArea includes the county (regional PPOs keep their counties). Individual MA plans only (HMO, PPO, PFFS, including SNPs); employer plans, PACE, cost plans and MSAs are excluded. Suppressed enrollment cells (1–10) count as 0.

Rebuild: `python3 ma-plan-exits/scripts/build_data.py`.
