# Counting to 218: the path to Medicare for All, 2027 to 2030

Page: https://usnish.xyz/medicare-for-all-votes/

What would have to happen, stage by stage from January 2027 through 2030, for Medicare for All (M4A) to become law, with the House and Senate count after each stage; the arithmetic of 218 House votes and 50 or 60 senators behind it; and every Democrat and Democratic-caucusing independent in the incoming 120th Congress with their stated position and its source. Counts as of 2026-11-12, nine days after the Nov 3, 2026 election.

## Findings (as shown on the page)

- House: 117 of 260 Democrats on record (95 returning sponsor and cosponsors of H.R.3069 plus 22 new members who have said they support it), 45% of the caucus, 101 short of 218.
- If every non-supporter in a safe seat (won by 15+ points) came over, 94 of them, the House would reach 211, still 7 short. 218 needs at least 7 of the 16 non-supporters in likely seats (8 to under 15 points), or about 50 more seats won at 2026's rate.
- 2026 pickups: 6 of about 43 Democratic House gains went to supporters (about 14%). At that rate, closing the 101-vote gap on new seats alone would take about 720 more seats, far more than the 175 Democrats do not already hold. The 43 is called flips as of Nov 12 (NBC 43, Fox 44); counting uncalled races Democrats lead it is about 47 (rate about 13%).
- Senate: 22 of 55 on record (18 returning sponsor and cosponsors of S.1506 plus El-Sayed, Stratton, Flanagan and Troy Jackson). 28 short of 50, 38 short of 60. Converting all 18 non-supporters outside states Trump won in 2024 or seats Republicans held before 2026 gives 40.
- 36 of 55 senators are on record for M4A, a public option or a Medicare buy-in.
- Trump can veto until Jan 20, 2029; an override needs 290 and 67. If signed in 2029, full benefits start in 2031 (H.R.3069) or Jan 1, 2033 (S.1506).
- The path (running counts are ceilings: every named member in a stage moves). House 117 -> 152 in 2027 (16 former cosponsors in any seat, then 19 safe-seat public-option/buy-in members) -> 215 through the 2028 primaries (the other 63 safe-seat Democrats: 20 ACA only, 42 no position, 1 against) -> exactly 218 with TN-9, ME-2 and CA-23 won by supporters and all 9 close-seat supporters held. Senate 22 -> 29 (7 named senators) -> 30 (Minnesota special, Nov 2, 2027) -> 32 (NY and PA seats, 2028 primaries) -> 34 (FL and WI pickups), 16 short of 50, against the Senate research's judgment of 32-37 by Jan 2029. 16 Democratic seats are up in 2028 (6 held by cosponsors), 19 in 2030 (8 supporters). Medicare-option fallback: 36 senators, 14 short of 50.
- Binding condition (the page's stated judgment): the Senate's 50th vote, and behind it a 2028 nominee who runs on M4A and wins.

## Sources

- Roster and positions: a research team of agents, Nov 12, 2026. Source files (not published; Jekyll skips `_viz/`, which is also untracked in git as of this writing, so commit `_viz/ideas/m4a-path/` if the build should be reproducible from the repo):
  - `_viz/ideas/m4a-path/members.json`: 326 rows (270 House incl. delegates and trailing candidates, 56 Senate incl. Alaska's uncalled race), each with position, quote, source URL, confidence, 2026 margin, seat rating and status. Corrected after a fact-check the same day.
  - `_viz/ideas/m4a-path/tallies.json` and `scripts/build_members.py`: the research team's counts.
  - `_viz/ideas/m4a-path/cosponsors_119.json`: sponsor and cosponsors of H.R.3069 and S.1506 with cosponsorship dates (congress.gov API cross-checked against [GovInfo BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr3069.xml) XML; H.R.3069 record updated 2026-10-23, [S.1506](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s1506.xml) 2026-09-26). Extracted from the research workflow's cosponsor scout on 2026-11-12.
- Hard-coded in `build_data.py` from the research team's path analysis: the 15 Senate non-supporters in states Trump won in 2024 or seats Republicans held before 2026 (Kelly, Gallego, Ossoff, Warnock, Cortez Masto, Rosen, Slotkin, Fetterman, Brown, Turek, Hamilton, Colom, Cooper, Andrews, Talarico), and the 2026 House gains (6 supporters of about 43: McGuire, Villegas, Mullock, Brooks, Lawrence, Padilla Stout). The script checks that each named member is in the roster with the expected position. Also hard-coded for the path, from the same research and checked against the roster: House pickup seats TN-9, ME-2, CA-23; the seven senators named first (Gallego, Murphy, Alsobrooks, Kim, Duckworth, Murray, Cantwell); the 2028 primary seats (Schumer, Fetterman; no challengers named); the Minnesota special (Klobuchar row); Senate pickups FL and WI.
- Static text on the page (polls, procedure, prior art, the named path) comes from the same research result, with the links it cited: KFF polling (66/34 Sept 2026; 52/47 if private insurers end), Gallup, Pew, Axios-Ipsos via Portside, the House Democrats' health working group memo, Newsweek (Jeffries), the coalition sign-on letter (no total stated; about 330 organizations counted), CRS RL30862 (Byrd rule), Healthcare-NOW 2021, Chaotic Era (Sept 2026), the Medicare for All PAC, Jayapal's cosponsor page, Legisletter, KFF's tracker, the Campaign for New York Health, GovInfo bill-status files for H.R.2045, H.R.10875, H.R.4406, S.4886, S.5700 and S.2286, Oregon's UHP board presentation (Oct 15, 2026) and NY S3425. Every external link on the page was checked against the research output; none were added from memory. One link was added in the Nov 12 pre-publication fact-check: KFF Health News on the 2020 platform committee vote, replacing an unsupported claim about 2024. The Nov 12 path revision added links, each opened before use and all cited in the research: GovInfo bill records for S.1804 (115th, 16 cosponsors), S.1129 (116th, 14) and S.1655 (118th, 14), which also corrected the page's earlier "14 in each of the three Congresses before"; Wikipedia (119th Congress committee leaders, 2028 convention dates, 2028 and 2030 Senate maps, Fetterman on the filibuster); the 2019 Rules, Budget and Ways and Means hearing pages; CBO working paper 2020-08 (RePEc); CRS 97-552 (discharge); KTTC (Minnesota special); FHQ's 2028 primary calendar; the Nevada Independent (Oct 2026 candidate forum); the Texas Tribune (Talarico on the filibuster); MS NOW (Dec 1 leader election); Warren's 2019 transition plan; KFF Health News (Oberlander quote).

## Method

- Counted: House voting members, with the leader of each uncalled race counted (CA-4 is Democrat vs Democrat and counted once, for Eric Jones; Mike Thompson is not counted). Not counted: the 4 delegates, trailing candidates in CA-23, NC-7 and AK-AL, and the LA-5 and LA-6 runoff candidates. Senate: 55 seated (53 D + 2 I); Mary Peltola (AK, uncalled) is shown but not counted. Klobuchar's row stands for her appointed successor.
- "On record" = position `cosponsor_119` (sponsor or cosponsor of the 119th bill who returns) or `supports_m4a` (new member with a public statement). Same rule as `build_members.py`.
- Seat ratings use the unofficial 2026 margin: competitive under 8 points, likely 8 to under 15, safe 15 or more.
- The House ladder adds disjoint groups in order: returning cosponsors, new supporters, past cosponsors in safe seats who are not on the current bill, then safe-seat non-supporters by position (public option or buy-in, ACA only, no position, opposed), then likely seats, then competitive seats.
- Dates: cosponsorship dates for cosponsors; for others, a date is shown only when exactly one full date (e.g. "Jan 14, 2026") appears in the research note for that member (22 of 202). Otherwise the card says the date was not recorded.
- `build_data.py` recomputes every count from `members.json` and stops if any differs from `tallies.json` (House 260/117/95/22, positions, ratings, the 16 past cosponsors; Senate 55/22/18). Every row must carry a source link (cosponsors link to the GovInfo bill-status file).
- Position colours were checked for colour-blind separation in light and dark mode (dataviz palette validator); "no position found" is an empty ring, never a fill, so it does not read as opposed.

## Output (`data/`)

- `members.json` (about 220 KB): one row per member with name, chamber, state, district, position and display group, confidence, quote, source URL, date, the research notes, 2026 margin and rating, past-cosponsor note, and whether the row is counted (and why not).
- `summary.json`: House and Senate counts, the `path` block (running counts for each timeline stage, Senate seats up in 2028 and 2030, the Medicare-option gap), the ladder groups with member names, holds (supporters in close seats against a Republican), uncalled leaders, soft supporters, the 2026 gains constant, the excluded rows, and a copy of the source tallies used for the check.

## Rebuild

```
python3 -I medicare-for-all-votes/scripts/build_data.py
```

Standard library only. To refresh positions, update `_viz/ideas/m4a-path/members.json`, rerun `_viz/ideas/m4a-path/scripts/build_members.py`, then this script.

## Limits

- 64 House members and 10 senators have no position found, mostly because the search budget ran out. Unknown, not opposed.
- Races not final: 6 House leaders counted in uncalled races (CA-4, NC-3, NC-5, TN-4, MN-1, CO-4), Alaska's Senate race (Nov 18), LA-5 and LA-6 runoffs (Dec 12). Mississippi's Senate race was called Nov 11 by about 0.5 points.
- Soft supporters (medium or low confidence): Eric Jones, Brad Lander, Micah Lasher, Katy Padilla Stout, Frederick Haynes III. Jasmine Clark (GA-13) is named as a supporter by The American Prospect (Nov 4, 2026) but has no statement here (would make 118). El-Sayed backs his own version, which he says would not have to ban extra coverage through unions or employers.
- Old statements: many non-supporter labels rest on 2009-2020 statements (Schumer, Reed, Rosen, Brown, Neal, McAdams, McBath, Bennet, Hickenlooper, Slotkin). Neal is coded ACA-only from his on-record 2019 remarks; the reported private criticism of M4A came from anonymous accounts. Fetterman is "no position found" (last statement 2020).
- One coder, spot-checked (32 rows; 4 overstated labels corrected). No second, independent coding.
- Margins are unofficial; seats near 15 points (CO-8, NY-19, CT-5, MI-3, NE-2) could change rating. Democrat-vs-Democrat California races are rated on the intra-party margin, so CA-7 (Matsui, non-supporter) reads as competitive; counting it safe makes the all-safe total 212.
- The 14% pickup rate is one election, and uses called gains only. The Senate best cases (32-37 by 2029, 38-44 by 2031) are the research team's judgment, not a model. That the Byrd rule would strike the bill's core is the team's inference; no M4A-specific ruling or CRS analysis was found.
- "No one has published this" rests on searches that did not cover Our Revolution, Justice Democrats, DSA's House Pressure Campaign (blocked) or the CalCare and Minnesota groups.

## Research conflicts and how they were resolved

- House supporters: research prose said 118 (and procedure research 119); the corrected `tallies.json` says 117 after Koh moved to public option. The page uses 117. All-safe-seats total: 213 in the prose, 211 in the data (CO-8 moved to likely; Koh). Page uses 211, gap 7.
- Senate no-position count: the brief said 9; corrected data has 10 (Fetterman moved from single payer in principle to no position). Page uses 10.
- Senators on record for M4A or a public Medicare option: Senate path research said 39 (counting Fetterman and three senators on record against M4A who backed a public option); the data's classification gives 36. Page uses 36.
- Senate "converting all 18 non-supporters outside Trump-won states gives 40": unchanged by the corrections (Fetterman is in the 15 swing-state group either way).
- Pre-publication fact-check (Nov 12): Richard Neal moved from opposed to ACA-only (the only quote against M4A was an anonymous account), so House opposed went from 5 to 4 and the safe-seat ladder step 'on record against' from 2 to 1; Daniel Biss moved to high confidence on his own site's words; Brad Lander's source switched to his own words; Cantwell's quote corrected; Peters and Auchincloss source URLs fixed. Supporter totals unchanged.
