# Can an AI write your prescription? One state, four pilots, and a wall of rules

Page: https://usnish.xyz/ai-prescribing-ladder/

Where AI may legally prescribe or renew medications, and how independently, on a four-rung ladder: (1) AI drafts and a clinician signs each prescription; (2) AI renews stable medications under a protocol with no signature on each script; (3) AI starts new prescriptions under a protocol; (4) AI is the prescriber of record in law. Alongside it, the wall of bans and human-must-decide rules, and the bills that would make AI a prescriber. Checked as of 2026-11-12.

## Findings (as shown on the page)

- Of the places checked, Utah is the only jurisdiction found that lets AI go past rung 1. It does so through 4 sandbox pilots under regulatory mitigation agreements: 3 allow renewals on paper (rung 2: Doctronic, Legion Health, August AI) and 1 allows new prescriptions (rung 3: Nolla Health, first-time topical acne).
- 2 have started (Doctronic, Phase 1; Nolla Health, Stage 1). In both a physician reviews every prescription before it goes out, so both operate at rung 1 today. Legion Health and August AI are listed as not started. Nothing operates above rung 1 anywhere found.
- Doctronic: the register (last changed 2026-10-06) still lists it as active, with a term that ran to 2026-10-24. No extension, suspension or end had been posted as of 2026-11-12. On 2026-04-20 the state medical licensing board recommended it "be immediately suspended pending further discussion" in a letter the state says 11 of 14 members signed; the state declined on 2026-04-21 because a physician reviews every renewal in Phase 1.
- Nolla Health: active 2026-10-05 to 2027-10-05; two physicians review every prescription in Stage 1.
- The wall: 39 entries. 13 adopted laws or binding rules, 9 guidance documents, 16 bills to restrict (11 failed, 5 pending), 1 draft. 7 are explicit bans naming AI (4 adopted). Outside the US, 11 countries have at least one rule on the wall (the UK's is the no-questionnaire-only prescribing rule); 5 have adopted one (Brazil, China, India, Italy, Poland). In the US, 6 states have adopted one (California, Delaware, New Mexico, Oregon, Tennessee, Texas), mostly title or general rules; bills to restrict were filed in 12 states. 9 of the adopted rules hold AI at rung 1 or lower.
- Moved to context: Fujian's internet care rules (valid two years from 2024-02-08 per art. 52; no renewal found).
- Bills to make AI a prescriber (rung 4): 4 found, 3 failed, 1 pending (federal H.R. 238, referred to Energy and Commerce 2025-01-07 with no action or cosponsors since; it dies when the 119th Congress ends in January 2027). The state bills were in Iowa and Idaho.
- Other sandboxes checked: Arizona's (no current participants), Wyoming's medical digital sandbox (no participants listed) and Texas's TRAIGA sandbox (no AI prescribing participant found). "Arizona SB 1847", cited in a blog as a renewal law, is the 2026 general appropriations act.

## Sources

Research files (not published; Jekyll skips `_viz/`, which is also untracked in git as of this writing, so commit `_viz/ideas/ai-prescribing/` if the build should be reproducible from the repo):

- `_viz/ideas/ai-prescribing/entries.json`: the first research pass (rows with jurisdiction, rung, status, legal basis, primary and secondary source URLs, confidence, notes).
- `entries_world_additions.json`, `entries_apac_additions.json`, `entries_us_state_bills.json` (with `us_state_sweep_report.md`): later passes on Europe and the rest of the world, Asia-Pacific, and US state bills.
- `entries_step1_additions.json`: the Nov 12 pass. Corrections to the Utah pilots (phase, start, review now), China's NMPA online prescription retail guide (now cited to its Xinhua legal text; the renewal reading rests on Sixth Tone only, confidence medium), H.R. 238 (GovInfo bill status), Texas sandbox notes; new rows for the Wyoming and Arizona sandboxes.
- `entries_factcheck_corrections.json`: the independent fact-check on 2026-11-12 (corrections only, each citing what was opened): China national rules now cited to the NHC Gazette PDF; Fujian lapsed; NMPA guide wording; India primary source moved to NRCeS; Brazil art. 5 s.2 (communication of decisions, not the decisions); Singapore circular number dropped; Australia guideline status; Saudi pilot wording; Abu Dhabi cited to TradeArabia; Tennessee signing date (2026-04-23); North Dakota and New Mexico citations; DEA wording; California AB 1979 verified from chaptered text; Oregon session law; H.R. 206 status; FSMB date. Also edited in place in the same pass: Illinois SB 2993 (status and notes; recoded human, not ban), Missouri SB 1012 and SB 1804 notes, New Jersey S4754 and Illinois SB 3702 status, Doctronic extension clause, and the prior-art records (Health & AI Policy Index, Manatt Q3 2026, NCSL, AI Laws by State, Live Compliance, OECD.AI).
- `searched_nothing_found_*.json`, `unverified_leads*.json` (including `unverified_leads_step1.json`), `prior_art.json`, `prior_art_step1.json`.
- Primary sources opened on 2026-11-12 for the step 1 pass, each linked on the page or in the data: Utah's authorized pilots register and each signed agreement, the medical board's letter and the state's reply (commerce.utah.gov), the board's 2026-03-19 agenda, azag.gov's sandbox participants page, Arizona's 2026 SB 1847 record, health.wyo.gov's sandbox page, GovInfo BILLSTATUS for H.R. 238, the Xinhua text of the NMPA guide, and the Health & AI Policy Index at healthaipolicy.org with its paper (doi 10.1038/s41746-026-02734-y). No link on the page was added from memory; every one comes from the data files or a page opened during research.

## Method

- `scripts/build_data.py` merges `entries.json`, then the world, Asia-Pacific, US state bill, step 1 and fact-check files, in that order. A record with a `corrects` field updates the entry it names (fields replaced, `other_urls` unioned); other records are added.
- Duplicates folded: `au-mba-telehealth-async-prescribing` into `au-mba-telehealth-async-rx`, and `au-ahpra-ai-guidance-2024` into `au-ahpra-ai-obligations`.
- The source schema is kept. Each row gains a hand-coded `group`, `strength`, `status_label`, `place` and `short` label (the `CODING` table in the script), plus `us`, `us_state`, `paper_rung` and `ceiling_rung`.
  - group: permission (allows AI past rung 1), bill_to_permit, restriction (adopted law or binding rule), guidance, bill_to_restrict, or context (background, not on the ladder or wall).
  - strength: explicit ban (names AI and bars it from prescribing, reviewing or holding a license), human must decide (a clinician makes the decision; not prescription-specific), title or personhood (AI may not use a clinician's title or is not a legal person), or no questionnaire-only prescribing (not AI-specific).
  - ceiling_rung: the source files used two rung conventions for restrictions (rungs addressed vs highest rung still allowed). `ceiling_rung` puts them on one scale, the highest rung a rule allows. The raw `rung` field is kept as given.
- Utah pilot phase, start and review-now text come from `UTAH_PILOTS` in the script, taken from the register and each agreement.
- The script stops if any row lacks a coding, a primary URL or a confidence; if anything operates above rung 1; or if permissions are not exactly the 4 Utah pilots.
- Every number in the page's prose is read from `summary.json` (dotted `data-k` paths), and the page asserts the key ones at load.
- Strength colours were checked for colour-blind separation in light and dark mode (dataviz palette validator). Every row also carries a text label, so colour is never the only cue.

## Output (`data/`)

- `entries.json`: 65 rows, one per law, rule, guidance, bill, pilot or context item, each with its primary source URL and confidence (56 high, 9 medium).
- `summary.json`: counts by group, status and confidence; the wall block (by strength, adopted countries and states); the Utah block (pilots, operating, board letter and reply dates); bills to permit; the 7 watch items; prior art; and coverage (13 places searched with nothing found, places not reached by region, 42 open leads, resolved leads, 29 corrections applied, duplicates merged).

## Rebuild

```
python3 -I ai-prescribing-ladder/scripts/build_data.py
```

Run from the repo root. Standard library only. Bump the `?v=` query string on the page's data fetches after a rebuild.

## Limits

- One coder, no second independent coding. Strength and ceiling are judgment calls on the text of each rule.
- Coverage is uneven. Places searched with nothing found and places not reached are listed on the page; Canadian provinces, most of Latin America, much of Asia, the Middle East and Africa, and several European countries were not reached. Absence from the page is not absence of a rule.
- 42 open leads, 7 from the Nov 12 pass: whether Doctronic's term was extended, Legion Health's start date (press reported a spring launch; the register says not started), whether the medical board voted formally, Texas DIR sandbox participants, a reported Doctronic application in Arizona, Wyoming participants, and the NMPA guide's renewal wording.
- Bills are coded at their last recorded action. Pending bills can move or die quickly; Pennsylvania's session ends November 30, 2026, so HB 1925 and HB 2678 should be re-marked failed after that date unless the Senate acts.
- China's NMPA guide: the ban on AI prescription review is in the legal text; the reading that it also covers renewals rests on one press source.
- Prior art: the Health & AI Policy Index (408 policies, last updated 2026-11-04) is the broader resource; its operational rule H1 groups prescribing with other reserved clinical functions. This page is narrower: one question, coded by autonomy rung. We found no other public tracker that maps AI prescribing rules across countries and US states by autonomy, but more than 20 candidate sources could not be checked (see `prior_art.json` coverage_limits).
- Not coded: state laws restricting AI in therapy and mental-health services (for example Illinois HB 1806, Nevada AB 406), which do not address prescribing.
- Not legal advice.
