"""Build the data files for the AI prescribing ladder page.

    python3 -I ai-prescribing-ladder/scripts/build_data.py

Reads the research files in _viz/ideas/ai-prescribing/ and writes:

    ai-prescribing-ladder/data/entries.json   one row per law, rule, bill, pilot or guidance
    ai-prescribing-ladder/data/summary.json   every count on the page, the watch list,
                                              prior art, coverage lists and open leads

Merge rules:
  1. entries.json is the canonical schema. The additions files are applied in order:
     world, apac, us_state_bills, step1, factcheck. A record with a "corrects" field replaces the
     fields it carries on the entry with that id; any other record is a new entry.
  2. Australia was coded twice (world and apac passes); each pair is merged into one
     entry, keeping the first id and the union of source URLs.
  3. Each entry gets the page fields below (group, strength, status label, place).
     Every entry must keep a primary source URL and a confidence.
No network access is needed.
"""
import json
import pathlib
import re
from collections import Counter, OrderedDict

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE.parent
REPO = PAGE.parent
SRC = REPO / "_viz" / "ideas" / "ai-prescribing"
OUT = PAGE / "data"

AS_OF = "2026-11-12"

ADDITIONS = ["entries_world_additions.json", "entries_apac_additions.json",
             "entries_us_state_bills.json", "entries_step1_additions.json",
             "entries_factcheck_corrections.json"]

# Duplicate Australia records: drop the second id, fold its URLs into the first.
DEDUPE = {
    "au-mba-telehealth-async-prescribing": "au-mba-telehealth-async-rx",
    "au-ahpra-ai-guidance-2024": "au-ahpra-ai-obligations",
}

# Page coding, one line per entry --------------------------------------------------------
# group:    permission | restriction | guidance | bill_to_permit | bill_to_restrict | context
#           (restriction = a ban or human-must-decide rule in a law, regulation or binding
#           professional code; guidance = the same kind of statement in non-binding text)
# strength: ban (names AI and bars it from prescribing, renewing, reviewing or holding a
#           prescriber's license) | human (a human must make the decision; general, not
#           prescription-specific) | title (title or personhood rule) | questionnaire
#           (limits questionnaire-only remote prescribing; not AI-specific) | None
# status:   enacted | regulation | guidance | bill_failed | bill_pending | draft | sandbox | pilot
CODING = {
    # id: (group, strength, status, place, short label)
    "us-ut-doctronic": ("permission", None, "sandbox", "Utah", "Doctronic: renewals of existing prescriptions"),
    "us-ut-legion": ("permission", None, "sandbox", "Utah", "Legion Health: psychiatric renewals"),
    "us-ut-august": ("permission", None, "sandbox", "Utah", "August AI: routine refills"),
    "us-ut-nolla": ("permission", None, "sandbox", "Utah", "Nolla Health: first-time topical acne prescriptions"),
    "us-ut-master-agreements": ("context", None, "sandbox", "Utah", "Master agreements with University of Utah Health and Intermountain"),
    "us-federal-hr238": ("bill_to_permit", None, "bill_pending", "U.S. federal", "H.R. 238, Healthy Technology Act of 2025"),
    "us-federal-hr206-118": ("bill_to_permit", None, "bill_failed", "U.S. federal", "H.R. 206, Healthy Technology Act of 2023"),
    "us-ia-hsb766": ("bill_to_permit", None, "bill_failed", "Iowa", "HSB 766, autonomous AI provider licensing"),
    "us-id-h945": ("bill_to_permit", None, "bill_failed", "Idaho", "H 945, Artificial Intelligence Medical Services Act"),
    "us-il-sb2993": ("bill_to_restrict", "human", "bill_pending", "Illinois", "SB 2993, no AI prescribing without physician control"),
    "us-ca-ab1979": ("restriction", "human", "enacted", "California", "AB 1979, no AI performing licensed clinical functions on its own"),
    "us-tx-sb1188": ("restriction", "human", "enacted", "Texas", "SB 1188, practitioner reviews AI-created records and discloses AI use"),
    "us-tx-traiga-sandbox": ("context", None, "enacted", "Texas", "AI regulatory sandbox (HB 149)"),
    "us-de-hb191": ("restriction", "ban", "enacted", "Delaware", "HB 191, no AI may be licensed as physician, nurse or PA"),
    "us-or-ors678027": ("restriction", "title", "enacted", "Oregon", "ORS 678.027, no nursing titles for AI"),
    "us-federal-fda-cds": ("context", None, "guidance", "U.S. federal", "FDA clinical decision support guidance"),
    "us-federal-dea-1306": ("context", None, "regulation", "U.S. federal", "DEA rule: controlled-substance prescriptions need an individual practitioner"),
    "us-ut-pharmacist-refill-nearneighbour": ("context", None, "regulation", "Utah", "Pharmacist emergency refill rule"),
    "cn-national-internet-dx-rules": ("restriction", "ban", "regulation", "China", "Internet diagnosis and treatment rules: no AI-generated prescriptions"),
    "cn-beijing-internet-dx-draft": ("restriction", "ban", "draft", "China (Beijing)", "Beijing internet care rules, 2023 draft"),
    # Fujian: art. 52 gives the rules a 2-year validity from 2024-02-08; no renewal found, so context, not wall
    "cn-fujian-internet-dx-rules": ("context", None, "regulation", "China (Fujian)", "Fujian internet care rules, lapsed February 2026"),
    "cn-hunan-hsa-pharmacy-notice": ("restriction", "ban", "regulation", "China (Hunan)", "Hunan medical insurance notice"),
    "cn-nmpa-online-rx-guidelines": ("guidance", "ban", "guidance", "China", "Online prescription drug retail guide: no AI prescription review"),
    "in-telemedicine-guidelines-2020": ("restriction", "ban", "regulation", "India", "Telemedicine Practice Guidelines: AI may not prescribe"),
    "jp-mhlw-ai-notice-2018": ("guidance", "human", "guidance", "Japan", "Health ministry notice: the physician decides and is responsible"),
    "br-cfm-2454-2026": ("restriction", "human", "regulation", "Brazil", "Medical council Resolution 2,454/2026: prescription always rests with the physician"),
    "sg-aihgle-2": ("guidance", "human", "guidance", "Singapore", "AI in Healthcare Guidelines 2.0: a human makes the final decision"),
    "ae-ad-doh-ai-clinician-framework": ("context", None, "guidance", "UAE (Abu Dhabi)", "AI Clinician Framework, research stage"),
    "sa-almoosa-synyi-pilot": ("context", None, "pilot", "Saudi Arabia", "Private AI clinic pilot, a doctor signs each plan"),
    "eu-ai-act": ("context", None, "regulation", "European Union", "EU AI Act"),
    "au-mba-telehealth-async-rx": ("guidance", "questionnaire", "guidance", "Australia", "Medical Board telehealth guidelines: no questionnaire-only prescribing"),
    "au-ahpra-ai-obligations": ("guidance", "human", "guidance", "Australia", "Ahpra: the practitioner stays responsible for AI output"),
    "ca-hc-mlmd-premarket-guidance": ("context", None, "guidance", "Canada", "Health Canada guidance on machine-learning devices"),
    "de-baek-ki-stellungnahme-2025": ("guidance", "human", "guidance", "Germany", "German Medical Association: therapy decisions may not be ceded to AI"),
    "it-legge-132-2025-art7": ("restriction", "human", "enacted", "Italy", "Law 132/2025, art. 7: the decision always rests with physicians"),
    "pl-kel-art12-ai": ("restriction", "human", "regulation", "Poland", "Code of Medical Ethics, art. 12: the physician takes the final decision"),
    "int-who-ai-health-guidance": ("context", None, "guidance", "World Health Organization", "WHO guidance on AI for health"),
    "gb-mhra-avt-guidance": ("context", None, "guidance", "United Kingdom", "MHRA: AI that places orders without review is a medical device"),
    "gb-gphc-distance-prescribing": ("guidance", "questionnaire", "guidance", "United Kingdom", "Pharmacy regulator: no questionnaire-only prescribing for listed medicines"),
    "nz-mcnz-ai-guidance-2026": ("guidance", "human", "guidance", "New Zealand", "Medical Council: registration cannot transfer to an AI"),
    "us-mo-sb1804": ("bill_to_restrict", "ban", "bill_failed", "Missouri", "SB 1804, no waivers for AI prescribing or renewals"),
    "us-mo-sb1012": ("bill_to_restrict", "human", "bill_failed", "Missouri", "SB 1012, professional keeps final authority over prescribing and renewals"),
    "us-nh-sb640": ("bill_to_restrict", "human", "bill_failed", "New Hampshire", "SB 640, no AI providing licensed services"),
    "us-nj-s4754": ("bill_to_restrict", "human", "bill_pending", "New Jersey", "S4754, AI output counts as unlicensed practice"),
    "us-mn-hf4979": ("bill_to_restrict", "human", "bill_failed", "Minnesota", "HF 4979, AI may not provide a professional service on its own"),
    "us-la-hb197": ("bill_to_restrict", "human", "bill_failed", "Louisiana", "HB 197, licensed review before AI treatment decisions"),
    "us-ok-sb2037": ("bill_to_restrict", "human", "bill_failed", "Oklahoma", "SB 2037, a licensed provider makes final decisions"),
    "us-ok-hb1915": ("bill_to_restrict", "human", "bill_failed", "Oklahoma", "HB 1915, physician validates AI output before care decisions"),
    "us-ms-hb1717": ("bill_to_restrict", "human", "bill_failed", "Mississippi", "HB 1717, clinician signs every AI order"),
    "us-in-sb180": ("bill_to_restrict", "human", "bill_failed", "Indiana", "SB 180 as introduced, AI may not substitute for a practitioner"),
    "us-hi-sb2281": ("bill_to_restrict", "human", "bill_failed", "Hawaii", "SB 2281, a person validates or overrides AI decisions"),
    "us-pa-hb1925": ("bill_to_restrict", "human", "bill_pending", "Pennsylvania", "HB 1925, AI may not supersede a clinician's decision"),
    "us-pa-hb2678": ("bill_to_restrict", "human", "bill_pending", "Pennsylvania", "HB 2678, boards must bar AI from acting independently"),
    "us-il-hb4804-sb3702": ("bill_to_restrict", "human", "bill_pending", "Illinois", "HB 4804 / SB 3702, AI may not substitute for nursing"),
    "us-nm-16.12-nmac-ai": ("restriction", "human", "regulation", "New Mexico", "Nursing board rules: AI is decision support only"),
    "us-tn-sb837": ("restriction", "title", "enacted", "Tennessee", "Pub. Ch. 781: AI is not a 'person' in state law"),
    "us-ca-ab489": ("restriction", "title", "enacted", "California", "AB 489, no license-implying terms for AI"),
    "us-va-hb146": ("context", None, "bill_failed", "Virginia", "HB 146, health sandbox that excluded prescribers"),
    "us-va-hb248": ("context", None, "bill_failed", "Virginia", "HB 248, licensing 'autonomous agents' (non-health boards)"),
    "us-nd-27.0359.01000": ("context", None, "draft", "North Dakota", "AI sandbox draft for the 2027 session"),
    "us-al-hb280-ky-sb175": ("context", None, "bill_failed", "Alabama and Kentucky", "State AI health platform bills that excluded prescribing"),
    "us-ks-sb405": ("bill_to_restrict", "title", "bill_failed", "Kansas", "SB 405, AI may not pose as a healthcare professional"),
    "us-fsmb-ai-policy-2024": ("guidance", "human", "guidance", "U.S. (FSMB)", "Federation of State Medical Boards AI policy"),
    "us-wy-medical-digital-sandbox": ("context", None, "enacted", "Wyoming", "Medical Digital Innovation Sandbox Act"),
    "us-az-regulatory-sandbox": ("context", None, "enacted", "Arizona", "Attorney General's regulatory sandbox"),
}

# Ladder placement for the Utah pilots: what the agreement allows on paper, and the review
# that applies today (from the state register, last modified 2026-10-06, and each pilot page).
UTAH_PILOTS = OrderedDict([
    ("us-ut-doctronic", {"phase_now": "Phase 1", "started": True,
                         "review_now": "A physician authorizes every renewal before it reaches the pharmacy.",
                         "next": "Phase 2 (AI sends renewals, physicians review after the fact) needs Utah AI office approval, medication group by medication group; not approved."}),
    ("us-ut-nolla", {"phase_now": "Stage 1", "started": True,
                     "review_now": "Two physicians review every prescription before it is sent.",
                     "next": "Stage 2 (AI submits, weekly review of all cases after the fact) needs written approval after at least 4 weeks and 100 patients."}),
    ("us-ut-legion", {"phase_now": "Not started", "started": False,
                      "review_now": "When it starts: a clinician reviews the first 250 requests before any completes.",
                      "next": "Then 1,000 with review after the fact, then monthly sampling."}),
    ("us-ut-august", {"phase_now": "Not started", "started": False,
                      "review_now": "When it starts: a provider reviews the first 250 refills before they reach the patient.",
                      "next": "Then 1,000 reviewed after the fact, then spot checks of at least 5% per medication class."}),
])

RUNGS = [
    {"n": 1, "name": "AI drafts, a clinician signs each prescription"},
    {"n": 2, "name": "AI renews stable medications under a protocol, no signature on each script"},
    {"n": 3, "name": "AI starts new prescriptions under a protocol"},
    {"n": 4, "name": "AI is the prescriber of record in law"},
]

US_PLACES_NOT_STATES = {"U.S. federal", "U.S. (FSMB)"}

# Old leads closed or replaced by the 2026-11-12 pass (matched on jurisdiction + start of lead)
SUPERSEDED_LEADS = [
    ("Arizona", "Arizona regulatory sandbox"), ("Wyoming", "AP (July 2026)"), ("Texas", "AP says Texas"),
    ("Utah", "A blog claimed Utah HB 249"), ("Utah", "Whether Doctronic's agreement"),
    ("China (national, NMPA)", "Exact Chinese title"),
    ("Australia", "Ahpra AI guidance"),  # now entries au-ahpra-ai-obligations and au-mba-telehealth-async-rx
    # repeated in a later pass, which is kept
    ("Estonia", "e-prescription allows doctor-issued"), ("Denmark", "Danish Medicines Agency piloting"),
    ("Shanghai", "Global Times/RFA say Shanghai issued"), ("China (national)", "NHC + 4 ministries"),
    ("South Korea", "MOHW AI Primary Healthcare Strategy (Aug 2026)"), ("United Kingdom", "No AI prescribing/renewal pilot found"),
    ("China (national)", "NHC + NDRC + MIIT"),  # verified and excluded: see RESOLVED
]
RESOLVED = [
    {"jurisdiction": "Utah", "lead": "A blog said Utah H.B. 249 (2026) lets AI approve renewals without physician review.",
     "resolution": "False: 2026 H.B. 249 is 'Federal Funds Modifications' (le.utah.gov)."},
    {"jurisdiction": "Arizona", "lead": "A blog table listed 'Arizona SB 1847' (March 2026) on prescription renewals.",
     "resolution": "No such bill on renewals: 2026 SB 1847 is the general appropriations act, signed 2026-06-13 (chapter 126). The Attorney General's sandbox lists no current participants."},
    {"jurisdiction": "China (national)", "lead": "NHC and four other bodies, opinions on 'AI + health care' (2025-10-20), first read as AI prescription authority.",
     "resolution": "Text verified: it promotes AI-assisted prescription review for primary care; no AI prescribing authority and no ban. Excluded."},
]

# Places with no research at all, compiled from the "Not searched" / "Not reached" rows of the
# leads files, less places a later pass reached (they are in entries or searched_nothing_found).
NOT_REACHED = [
    {"region": "Europe", "places": ["Netherlands", "Spain", "Switzerland", "Portugal", "Finland", "Iceland", "Latvia", "Ukraine", "Scotland and Wales (UK devolved rules)"],
     "note": "Netherlands, Spain, Switzerland and Portugal have open leads (professional codes, prescription statutes) that were not opened."},
    {"region": "Americas", "places": ["Canadian provinces and their colleges of physicians", "Mexico", "Argentina", "Chile", "Colombia", "the rest of Latin America"],
     "note": "Health Canada's federal device guidance is coded; provinces set prescribing rules and were not checked."},
    {"region": "Asia", "places": ["Taiwan", "Indonesia", "Philippines", "Thailand", "Vietnam", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Kazakhstan", "Uzbekistan", "other Chinese provinces"],
     "note": "South Korea was searched but its law database was not reached; India's 2023 NMC conduct regulations and Japan's online-care guideline were not read for AI text."},
    {"region": "Middle East", "places": ["Gulf states other than Abu Dhabi and Saudi Arabia (including Dubai)", "Israel", "the rest of the region"],
     "note": "Dubai and Israel have open leads only."},
    {"region": "Africa", "places": ["Kenya", "Nigeria", "Rwanda", "South Africa", "Ghana", "the rest of Africa"],
     "note": "Ghana's 2024 ePharmacy policy is an open lead."},
    {"region": "United States", "places": ["Georgia's legislature (site blocked)", "most state medical, nursing and pharmacy boards"],
     "note": "Every state's 2025-26 bills were swept through NCSL's database and most legislatures' own sites; board rules were spot-checked only."},
]

# What to watch: dates are fixed facts; status text is pulled from the entries.
WATCH = [
    ("us-pa-hb1925", "Pennsylvania HB 1925 in the Senate",
     "The 2025-26 session ends November 30, 2026; the bill dies if the Senate does not act."),
    ("us-nj-s4754", "New Jersey S4754",
     "The 2026-27 session runs to January 2028, so it can still move."),
    ("us-nd-27.0359.01000", "North Dakota's AI sandbox draft",
     "The Legislature meets in January 2027. As drafted it would let AI be tested without a license, health care included, with no carve-out for prescribing."),
    ("us-federal-hr238", "H.R. 238 in Congress",
     "It dies when the 119th Congress ends in early January 2027 unless it is reintroduced."),
    ("us-ut-doctronic", "Utah: Doctronic's term and Phase 2",
     "Its listed term ended October 24, 2026 with no extension posted. The Utah AI office reports to the Legislature before November 30 each year."),
    ("us-ut-legion", "Utah: Legion Health and August AI start dates",
     "Both are approved but not started; each starts with clinician review of every request."),
    ("us-il-sb2993", "Illinois SB 2993",
     "The 104th General Assembly ends in January 2027."),
]


def load(name):
    return json.loads((SRC / name).read_text())


def union_urls(*lists):
    out = []
    for lst in lists:
        for u in lst or []:
            if isinstance(u, str) and u.startswith("http") and u not in out:
                out.append(u)
    return out


def main():
    base = load("entries.json")
    schema = list(base[0].keys())
    entries = OrderedDict((e["id"], dict(e)) for e in base)
    corrections = []
    for f in ADDITIONS:
        for rec in load(f):
            rec = dict(rec)
            target = rec.pop("corrects", None)
            if target:
                assert target in entries, f"{f}: corrects unknown id {target}"
                before = entries[target]
                changed = [k for k, v in rec.items() if k != "id" and before.get(k) != v]
                # other_urls accumulate; everything else is replaced
                if "other_urls" in rec:
                    rec["other_urls"] = union_urls(rec["other_urls"], before.get("other_urls"))
                before.update({k: v for k, v in rec.items() if k != "id"})
                corrections.append({"id": target, "file": f, "fields": changed})
            else:
                assert rec["id"] not in entries, f"{f}: duplicate id {rec['id']}"
                entries[rec["id"]] = rec

    for drop, keep in DEDUPE.items():
        a, b = entries[keep], entries.pop(drop)
        a["other_urls"] = union_urls(a.get("other_urls"), [b.get("primary_source_url"), b.get("secondary_source_url")], b.get("other_urls"))
        a["other_urls"] = [u for u in a["other_urls"] if u != a.get("primary_source_url")]
        if not a.get("expiry") and b.get("expiry"):
            a["expiry"] = b["expiry"]
        a["notes"] = (a.get("notes") or "") + f" Merged with duplicate record {drop} from a second research pass."

    missing = set(entries) ^ set(CODING)
    assert not missing, f"coding table and entries differ: {sorted(missing)}"

    rows = []
    for eid, e in entries.items():
        assert e.get("primary_source_url", "").startswith("http"), f"{eid}: no primary source URL"
        assert e.get("confidence") in ("high", "medium", "low"), f"{eid}: no confidence"
        group, strength, status, place, short = CODING[eid]
        row = {k: e.get(k) for k in schema}
        # other_urls in the source files are sometimes free text; keep only links
        raw = e.get("other_urls") or []
        row["other_urls"] = [u for u in raw if isinstance(u, str) and u.startswith("http")]
        row["other_urls_text"] = [u for u in raw if isinstance(u, str) and not u.startswith("http")] or None
        row["rung"] = None if e.get("rung") is None else str(e.get("rung"))
        row.update({
            "group": group, "strength": strength, "status_label": status, "place": place, "short": short,
            "us": e.get("country") == "United States",
            "us_state": e.get("country") == "United States" and place not in US_PLACES_NOT_STATES,
        })
        # rung semantics: for permissions and bills to permit, the rung allowed on paper; the
        # US sweep coded restrictions as the highest rung still allowed, entries.json as the
        # rungs addressed. ceiling_rung puts both on one scale: the highest rung a rule allows.
        if group == "permission":
            row["paper_rung"] = int(str(e["rung"])[0])
            row.update(UTAH_PILOTS[eid])
        elif group == "bill_to_permit":
            row["paper_rung"] = 4
        if group in ("restriction", "guidance", "bill_to_restrict"):
            r = row["rung"]
            row["ceiling_rung"] = 3 if r == "4" else (1 if r in ("1", "2-4", "2", "3") else None)
        rows.append(row)

    # sort: group order, then place
    gorder = ["permission", "bill_to_permit", "restriction", "guidance", "bill_to_restrict", "context"]
    rows.sort(key=lambda r: (gorder.index(r["group"]), not r["us"], r["place"], r["id"]))

    # ---- counts ---------------------------------------------------------------------------
    by = lambda key, rs: dict(Counter(r[key] for r in rs))
    perm = [r for r in rows if r["group"] == "permission"]
    operating = [r for r in perm if r["operating_rung_now"] is not None]
    wall = [r for r in rows if r["group"] in ("restriction", "guidance", "bill_to_restrict")]
    adopted = [r for r in wall if r["status_label"] in ("enacted", "regulation")]
    bills_permit = [r for r in rows if r["group"] == "bill_to_permit"]
    bills_restrict = [r for r in rows if r["group"] == "bill_to_restrict"]
    world_wall = [r for r in wall if not r["us"]]
    country = lambda r: r["place"].split(" (")[0]
    world_countries = sorted({country(r) for r in world_wall})
    world_adopted_countries = sorted({country(r) for r in world_wall if r["status_label"] in ("enacted", "regulation")})
    us_adopted_states = sorted({r["place"] for r in adopted if r["us_state"]})
    us_bill_states = sorted({p for r in bills_restrict for p in [r["place"]]})
    explicit = [r for r in wall if r["strength"] == "ban"]

    assert all(r["operating_rung_now"] in (None, 1) for r in rows), "something operates above rung 1; revise the page text"
    assert len(perm) == 4 and all(r["place"] == "Utah" for r in perm)

    nothing_found = []
    for f in ["searched_nothing_found_world.json", "searched_nothing_found_apac.json"]:
        for x in load(f):
            nothing_found.append({"place": x["country"], "finding": x.get("result") or x.get("notes"),
                                  "checked": x.get("date_checked") or "2026-11-12"})

    leads = []
    for f in ["unverified_leads.json", "unverified_leads_world.json", "unverified_leads_apac.json", "unverified_leads_step1.json"]:
        for x in load(f):
            j, lead = x["jurisdiction"], x["lead"]
            if j.startswith("Not ") or j == "Not searched":
                continue
            if f != "unverified_leads_step1.json" and any(j == sj and lead.startswith(sl) for sj, sl in SUPERSEDED_LEADS):
                continue
            leads.append({"jurisdiction": j, "lead": lead, "why_unverified": x["why_unverified"], "file": f})

    prior = load("prior_art.json")
    prior_items = load("prior_art_step1.json") + prior["items"]

    ent = {r["id"]: r for r in rows}
    watch = [{"id": i, "title": t, "status": ent[i]["status_detail"] or ent[i]["status"], "why": w,
              "url": ent[i]["primary_source_url"]} for i, t, w in WATCH]

    summary = {
        "as_of": AS_OF,
        "rungs": RUNGS,
        "entries": len(rows),
        "by_group": by("group", rows),
        "by_status": by("status_label", rows),
        "by_confidence": by("confidence", rows),
        "context": len([r for r in rows if r["group"] == "context"]),
        "wall": {
            "total": len(wall),
            "adopted": len(adopted),
            "guidance": sum(r["group"] == "guidance" for r in wall),
            "bills": len(bills_restrict),
            "bills_failed": sum(r["status_label"] == "bill_failed" for r in bills_restrict),
            "bills_pending": sum(r["status_label"] == "bill_pending" for r in bills_restrict),
            "drafts": sum(r["status_label"] == "draft" for r in wall),
            "by_strength": by("strength", wall),
            "explicit_bans": len(explicit),
            "explicit_bans_adopted": sum(r["status_label"] in ("enacted", "regulation") for r in explicit),
            "world_countries": world_countries,
            "world_countries_n": len(world_countries),
            "world_adopted_countries": world_adopted_countries,
            "world_adopted_countries_n": len(world_adopted_countries),
            "us_adopted_states": us_adopted_states,
            "us_adopted_states_n": len(us_adopted_states),
            "us_bill_states": us_bill_states,
            "us_bill_states_n": len(us_bill_states),
            "ceiling_1_adopted": sum(r.get("ceiling_rung") == 1 for r in adopted),
        },
        "utah": {
            "pilots": len(perm),
            "jurisdictions_permitting": len({r["place"] for r in perm}),
            "operating": len(operating),
            "operating_ids": [r["id"] for r in operating],
            "not_started": len(perm) - len(operating),
            "paper_rung_max": max(r["paper_rung"] for r in perm),
            "paper_rung_2": sum(r["paper_rung"] == 2 for r in perm),
            "paper_rung_3": sum(r["paper_rung"] == 3 for r in perm),
            "operating_above_rung_1": sum((r["operating_rung_now"] or 0) > 1 for r in rows),
            "register_modified": "2026-10-06",
            # From the signed agreements, the register and the board correspondence (opened 2026-11-12)
            "term_months": 12,
            "doctronic_term_end": "2026-10-24",
            "board_letter_date": "2026-04-20",
            "board_signers": 11,
            "board_members": 14,
            "state_reply_date": "2026-04-21",
        },
        "bills_to_permit": {
            "total": len(bills_permit),
            "failed": sum(r["status_label"] == "bill_failed" for r in bills_permit),
            "pending": sum(r["status_label"] == "bill_pending" for r in bills_permit),
            "ids": [r["id"] for r in sorted(bills_permit, key=lambda r: r["source_date"])],
            "states_n": len({r["place"] for r in bills_permit if r["us_state"]}),
        },
        "watch": watch,
        "prior_art": {"checked_on": prior["checked_on"], "verdict_detail": prior["verdict_detail"],
                      "coverage_limits": prior["coverage_limits"], "items": prior_items},
        "coverage": {
            "searched_nothing_found": nothing_found,
            "searched_nothing_found_n": len(nothing_found),
            "not_reached": NOT_REACHED,
            "open_leads": leads,
            "open_leads_n": len(leads),
            "resolved_leads": RESOLVED,
            "corrections_applied": corrections,
            "duplicates_merged": [{"dropped": d, "kept": k} for d, k in DEDUPE.items()],
        },
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "entries.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    w = summary["wall"]
    print(f"{len(rows)} entries; groups {summary['by_group']}")
    print(f"wall {w['total']} (adopted {w['adopted']}, guidance {w['guidance']}, bills {w['bills']} = {w['bills_failed']} failed + {w['bills_pending']} pending)")
    print(f"utah {summary['utah']}")
    print(f"bills to permit {summary['bills_to_permit']}")
    print(f"corrections {len(corrections)}, leads {len(leads)}, nothing found {len(nothing_found)}")


if __name__ == "__main__":
    main()
