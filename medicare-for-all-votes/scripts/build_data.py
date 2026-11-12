"""Build the data files for the Medicare for All votes page.

    python3 -I medicare-for-all-votes/scripts/build_data.py

Reads the research roster in _viz/ideas/m4a-path/ (members.json, tallies.json,
cosponsors_119.json) and writes:

    medicare-for-all-votes/data/members.json   one row per member, only the fields the page uses
    medicare-for-all-votes/data/summary.json   counts, the ladder blocs and the research constants

Every count is recomputed from members.json with the same rules as
_viz/ideas/m4a-path/scripts/build_members.py and checked against tallies.json.
The script stops if they disagree, so the page cannot drift from the source.
No network access is needed.
"""
import json
import pathlib
import re
import unicodedata
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE.parent
REPO = PAGE.parent
SRC = REPO / "_viz" / "ideas" / "m4a-path"
OUT = PAGE / "data"

AS_OF = "2026-11-12"

# Same rules as build_members.py --------------------------------------------------------
SUPPORT = {"cosponsor_119", "supports_m4a"}
NONVOTING = {"DC", "PR", "VI", "GU"}
NOT_SEATED = {
    ("House", "NC-7"): "Trailing in an uncalled race",
    ("House", "CA-23"): "Trailing in an uncalled race",
    ("House", "AK-AL"): "Trailing in an uncalled race (independent)",
    ("House", "LA-5"): "In the Dec 12 runoff",
    ("House", "LA-6"): "In the Dec 12 runoff",
}
CA4_SKIP = ("House", "CA-4", "Mike Thompson")
SENATE_PENDING = {"Mary Peltola": "Alaska race uncalled (ranked-choice count Nov 18)"}

# Display groups. Public option and Medicare buy-in or lower age share a colour.
GROUP = {
    "cosponsor_119": "cos",
    "supports_m4a": "new",
    "supports_single_payer_in_principle": "new",
    "public_option": "opt",
    "lower_medicare_age_or_buy_in": "opt",
    "strengthen_aca_only": "aca",
    "opposes_m4a": "opp",
    "no_position_found": "unk",
}

# Constants from the research team's path work (journal, Nov 12, 2026). Not derivable from members.json.
# Senate non-supporters in states Trump won in 2024 or in seats Republicans held before 2026
# (Senate path research, step 3c). The script checks each is a seated non-supporter.
SENATE_SWING = ["Mark Kelly", "Ruben Gallego", "Jon Ossoff", "Raphael Warnock", "Catherine Cortez Masto",
                "Jacky Rosen", "Elissa Slotkin", "John Fetterman", "Sherrod Brown", "Josh Turek",
                "Adam Hamilton", "Scott Colom", "Roy Cooper", "Annie Andrews", "James Talarico"]
# 2026 Democratic House gains that went to M4A supporters (House path research): 6 of about 43.
GAINS_TOTAL = 43
GAINS_SUPPORTERS = ["Mike McGuire", "Randy Villegas", "Zack Mullock", "Bob Brooks", "William Lawrence",
                    "Katy Padilla Stout"]

# The path forward (2027-2030). The named seats and members come from the research team's path work and
# were already on the page; the counts are computed here. Each one is checked against the roster below.
# House seats Republicans won or lead in 2026 where the Democratic nominee ran on M4A (CA-23's Democrat
# trails in an uncalled race and is not counted).
HOUSE_PICKUPS = ["TN-9", "ME-2", "CA-23"]
# Senators the Senate path research named as needing to change position first, in its order.
SENATE_PERSUADE = ["Ruben Gallego", "Chris Murphy", "Angela Alsobrooks", "Andy Kim", "Tammy Duckworth",
                   "Patty Murray", "Maria Cantwell"]
# Seats with 2028 primaries the research named (New York and Pennsylvania). No challengers are named.
SENATE_PRIMARY = ["Chuck Schumer", "John Fetterman"]
# Minnesota: Klobuchar's row stands for her appointed successor until the Nov 2, 2027 special election.
SENATE_SPECIAL = "Amy Klobuchar"
# Republican-held 2028 seats where the research said a supporter could be the Democratic nominee.
SENATE_PICKUPS_2028 = ["Florida", "Wisconsin"]

HOUSE_XML = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr3069.xml"
SENATE_XML = "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s1506.xml"

DVD_RE = re.compile(r"(?:over|vs) (?:Rep\. )?[^,()]+, D\)")
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d\d"
    r"|\b(?:19|20)\d\d-\d\d-\d\d")


def last_name(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    n = re.sub(r"\([^)]*\)", " ", n)                      # "Bernard (Bernie) Sanders"
    n = re.sub(r"\b(Jr|Sr|II|III)\.?$", "", n.strip()).strip(" ,")
    return n.split()[-1].lower()


def main():
    rows = json.loads((SRC / "members.json").read_text(encoding="utf-8"))
    tallies = json.loads((SRC / "tallies.json").read_text(encoding="utf-8"))
    cos = json.loads((SRC / "cosponsors_119.json").read_text(encoding="utf-8"))

    cos_idx = {}
    for ch, key in (("House", "house"), ("Senate", "senate")):
        for c in cos[key]:
            cos_idx[(ch, c["state"], last_name(c["name"]))] = c

    lapsed_rule = lambda r: (r["position"] not in SUPPORT and
                             (r.get("past_cosponsor") or "").lower().startswith(("yes", "cosponsored", "h.r.676")))

    out, missing_dates = [], []
    for r in rows:
        ch = r["chamber"]
        why = ""
        if ch == "House":
            if r["state"] in NONVOTING:
                why = "Nonvoting delegate"
            elif (ch, r["district"]) in NOT_SEATED:
                why = NOT_SEATED[(ch, r["district"])]
            elif (ch, r["district"], r["name"]) == CA4_SKIP:
                why = "Trailing in a Democrat-vs-Democrat race (CA-4); the seat is counted once, for the leader"
        elif r["name"] in SENATE_PENDING:
            why = SENATE_PENDING[r["name"]]

        pos = r["position"]
        quote, src, date, how = r.get("quote") or "", r.get("source_url") or "", "", ""
        if pos == "cosponsor_119":
            c = cos_idx.get((ch, r["state"], last_name(r["name"])))
            bill = "H.R.3069" if ch == "House" else "S.1506"
            src = HOUSE_XML if ch == "House" else SENATE_XML
            if c:
                date = c["date"]
                how = f"{'Sponsor' if c['role'] == 'sponsor' else 'Cosponsor'} of {bill}, the Medicare for All Act"
            else:
                how = f"Sponsor or cosponsor of {bill}, the Medicare for All Act"
                missing_dates.append(r["name"])
        else:
            found = sorted(set(DATE_RE.findall(r.get("pos_note") or "")))
            if len(found) == 1:
                date = found[0]

        out.append({
            "n": r["name"], "ch": "H" if ch == "House" else "S", "st": r["state"], "d": r["district"],
            "pos": pos, "g": GROUP[pos], "conf": r["confidence"],
            "q": quote, "how": how, "src": src, "dt": date,
            "pn": (r.get("pos_note") or "").strip(), "sn": (r.get("note") or "").strip(),
            "past": (r.get("past_cosponsor") or "").strip() if lapsed_rule(r) else "",
            "lapsed": 1 if (lapsed_rule(r) and not why) else 0,
            "status": r["status"], "rating": r["seat_rating"], "margin": r["margin_2026"],
            "next": r["next_election"], "party": r.get("party", "D"),
            "counted": 0 if why else 1, "why": why,
            # Democrat-vs-Democrat general (California top-two): the margin is intra-party
            "dvd": 1 if DVD_RE.search(r["margin_2026"] or "") else 0,
        })

    # Every classification needs a source link
    no_src = [m["n"] for m in out if not m["src"]]
    assert not no_src, f"rows without a source link: {no_src}"
    assert not missing_dates, f"cosponsors not matched to the cosponsor list: {missing_dates}"

    H = [m for m in out if m["ch"] == "H" and m["counted"]]
    Sn = [m for m in out if m["ch"] == "S" and m["counted"]]
    sup = lambda m: m["pos"] in SUPPORT

    # Check against tallies.json ----------------------------------------------------------
    def check(name, mine, theirs):
        assert mine == theirs, f"{name}: page data {mine} != tallies.json {theirs}"

    check("house voting seated", len(H), tallies["house_voting_seated_likely"])
    check("house supporters", sum(map(sup, H)), tallies["house_supporters"])
    check("house returning cosponsors", sum(m["pos"] == "cosponsor_119" for m in H),
          tallies["house_cosponsor_119_returning"])
    check("house new supporters", sum(m["pos"] == "supports_m4a" for m in H), tallies["house_supports_m4a_new"])
    check("house positions", dict(Counter(m["pos"] for m in H)), tallies["house_position"])
    check("house nonsupporter by rating", dict(Counter(m["rating"] for m in H if not sup(m))),
          tallies["house_nonsupporter_by_rating"])
    check("house safe nonsupporters by position",
          dict(Counter(m["pos"] for m in H if not sup(m) and m["rating"] == "safe")),
          tallies["house_nonsupporter_safe_by_position"])
    check("house supporter by rating", dict(Counter(m["rating"] for m in H if sup(m))),
          tallies["house_supporter_by_rating"])
    check("house lapsed", sorted(f'{m["d"]} {m["n"]}' for m in H if m["lapsed"]),
          tallies["house_dropped_off_past_cosponsor"])
    check("senate seated", len(Sn), tallies["senate_seated_caucus"])
    check("senate supporters", sum(map(sup, Sn)), tallies["senate_supporters"])
    check("senate cosponsors", sum(m["pos"] == "cosponsor_119" for m in Sn), tallies["senate_cosponsor_119"])

    # House ladder: disjoint blocs, in order ----------------------------------------------
    nonsup = [m for m in H if not sup(m)]
    used = set()

    def bloc(key, label, pred):
        mem = [m for m in H if id(m) not in used and pred(m)]
        used.update(id(m) for m in mem)
        return {"key": key, "label": label, "n": len(mem),
                "by_pos": dict(Counter(m["pos"] for m in mem)), "names": [f'{m["n"]} ({m["d"]})' for m in mem]}

    safe = lambda m: m["rating"] == "safe"
    ladder = [
        bloc("cos", "Returning sponsor and cosponsors of H.R.3069", lambda m: m["pos"] == "cosponsor_119"),
        bloc("new", "New members on record for M4A", lambda m: m["pos"] == "supports_m4a"),
        bloc("lapsed", "Past cosponsors in safe seats who are not on the current bill", lambda m: m["lapsed"] and safe(m)),
        bloc("safe_opt", "Safe seats: public option or Medicare buy-in", lambda m: safe(m) and m["g"] == "opt"),
        bloc("safe_aca", "Safe seats: strengthen the ACA only", lambda m: safe(m) and m["g"] == "aca"),
        bloc("safe_unk", "Safe seats: no position found", lambda m: safe(m) and m["g"] == "unk"),
        bloc("safe_opp", "Safe seats: on record against M4A", lambda m: safe(m) and m["g"] == "opp"),
        bloc("likely", "Likely seats (won by 8 to 15 points), all non-supporters", lambda m: m["rating"] == "likely"),
        bloc("comp", "Competitive seats (won by under 8 points), all non-supporters", lambda m: True),
    ]
    assert sum(b["n"] for b in ladder) == len(H)
    cum = 0
    for b in ladder:
        cum += b["n"]
        b["cum"] = cum
    after_safe = next(b["cum"] for b in ladder if b["key"] == "safe_opp")
    check("all safe-seat non-supporters", after_safe - tallies["house_supporters"],
          tallies["house_nonsupporter_by_rating"]["safe"])

    # Senate --------------------------------------------------------------------------------
    by_name = {m["n"]: m for m in Sn}
    for n in SENATE_SWING:
        assert n in by_name and not sup(by_name[n]), f"SENATE_SWING name not a seated non-supporter: {n}"
    s_sup = [m for m in Sn if sup(m)]
    s_other = [m for m in Sn if not sup(m) and m["n"] not in SENATE_SWING]
    s_swing = [m for m in Sn if m["n"] in SENATE_SWING]
    for m in out:
        if m["ch"] == "S":
            m["swing"] = 1 if m["n"] in SENATE_SWING else 0
    senate = {
        "seated": len(Sn),
        "supporters": len(s_sup),
        "cosponsors": sum(m["pos"] == "cosponsor_119" for m in Sn),
        "new_supporters": sorted(m["n"] for m in Sn if m["pos"] == "supports_m4a"),
        "other_states": len(s_other),
        "other_states_names": sorted(m["n"] for m in s_other),
        "swing": len(s_swing),
        "if_all_other_states": len(s_sup) + len(s_other),
        "positions": dict(Counter(m["pos"] for m in Sn)),
        "medicare_option": len(s_sup) + sum(m["g"] == "opt" for m in Sn),
        "pending": [m["n"] for m in out if m["ch"] == "S" and not m["counted"]],
        "by_next_election": tallies["senate_by_next_election"],
    }

    for n in GAINS_SUPPORTERS:
        m = next((x for x in H if x["n"] == n), None)
        assert m and sup(m), f"gain supporter not a counted supporter: {n}"

    house = {
        "seated": len(H),
        "supporters": sum(map(sup, H)),
        "cosponsors": sum(m["pos"] == "cosponsor_119" for m in H),
        "new_supporters": sum(m["pos"] == "supports_m4a" for m in H),
        "gap_218": 218 - sum(map(sup, H)),
        "positions": dict(Counter(m["pos"] for m in H)),
        "nonsupporter_by_rating": dict(Counter(m["rating"] for m in nonsup)),
        "supporter_by_rating": dict(Counter(m["rating"] for m in H if sup(m))),
        "all_safe": after_safe,
        "lapsed": [f'{m["n"]} ({m["d"]})' for m in H if m["lapsed"]],
        "lapsed_n": sum(m["lapsed"] for m in H),
        "supporters_not_safe": [f'{m["n"]} ({m["d"]}, {m["rating"]})' for m in H if sup(m) and m["rating"] != "safe"],
        # Supporters in close seats against a Republican (Democrat-vs-Democrat races left out)
        "holds": [f'{m["n"]} ({m["d"]})' for m in H if sup(m) and m["rating"] != "safe" and not m["dvd"]],
        "dvd_nonsafe_nonsupporters": [f'{m["n"]} ({m["d"]})' for m in nonsup if m["dvd"] and m["rating"] != "safe"],
        "uncalled_leaders": [f'{m["n"]} ({m["d"]})' for m in H if m["status"] == "uncalled"],
        "confidence_nonsupporters": dict(Counter(m["conf"] for m in nonsup)),
        "soft_supporters": [f'{m["n"]} ({m["d"]})' for m in H if sup(m) and m["conf"] in ("medium", "low")],
    }
    gains_rate = len(GAINS_SUPPORTERS) / GAINS_TOTAL

    # Path forward: running counts if every member in each group moved ---------------------
    # House groups are disjoint and taken in timeline order.
    nm = lambda m: f'{m["n"]} ({m["d"]})'
    h_lapsed = [m for m in H if m["lapsed"]]
    h_near = [m for m in H if safe(m) and not sup(m) and not m["lapsed"] and m["g"] == "opt"]
    h_rest = [m for m in H if safe(m) and not sup(m) and not m["lapsed"] and m["g"] != "opt"]
    h_likely = [m for m in H if m["rating"] == "likely" and not sup(m) and not m["lapsed"]]
    h_holds = house["holds"]
    for d in HOUSE_PICKUPS:
        assert not any(m["d"] == d for m in H), f"pickup seat already held by a counted Democrat: {d}"
    # Every safe-seat non-supporter is in exactly one of the three groups
    safe_non = [m for m in H if safe(m) and not sup(m)]
    assert {id(m) for m in safe_non} <= {id(m) for m in h_lapsed + h_near + h_rest}
    assert len({id(m) for m in h_lapsed + h_near + h_rest}) == len(h_lapsed) + len(h_near) + len(h_rest)
    h0 = house["supporters"]
    h1 = h0 + len(h_lapsed)
    h2 = h1 + len(h_near)
    h3 = h2 + len(h_rest)
    h4 = h3 + len(HOUSE_PICKUPS)
    assert h3 == after_safe + sum(1 for m in h_lapsed if not safe(m)), "path and ladder disagree"

    s_by = {m["n"]: m for m in Sn}
    for n in SENATE_PERSUADE + SENATE_PRIMARY + [SENATE_SPECIAL]:
        assert n in s_by and not sup(s_by[n]), f"path senator not a seated non-supporter: {n}"
    assert not set(SENATE_PERSUADE) & set(SENATE_PRIMARY + [SENATE_SPECIAL])
    s0 = senate["supporters"]
    s1 = s0 + len(SENATE_PERSUADE)
    s2 = s1 + 1                                   # Minnesota special
    s3 = s2 + len(SENATE_PRIMARY)
    s4 = s3 + len(SENATE_PICKUPS_2028)
    moved = set(SENATE_PERSUADE + SENATE_PRIMARY + [SENATE_SPECIAL])
    s_left = [m for m in Sn if not sup(m) and m["n"] not in moved]
    by_next = dict(Counter(m["next"] for m in Sn))
    check("senate by next election", by_next, tallies["senate_by_next_election"])
    up = lambda y: [m for m in Sn if m["next"] == y]
    s_opt_rest = [m for m in Sn if not sup(m) and m["g"] != "opt"]
    path = {
        "house": {
            "start": h0,
            "lapsed": {"n": len(h_lapsed), "after": h1, "names": [nm(m) for m in h_lapsed],
                       "not_safe": [nm(m) for m in h_lapsed if not safe(m)]},
            "near": {"n": len(h_near), "after": h2, "by_pos": dict(Counter(m["pos"] for m in h_near)),
                     "names": [nm(m) for m in h_near]},
            "rest_safe": {"n": len(h_rest), "after": h3, "by_pos": dict(Counter(m["pos"] for m in h_rest))},
            "pickups": {"seats": HOUSE_PICKUPS, "n": len(HOUSE_PICKUPS), "after": h4},
            "holds_n": len(h_holds),
            "likely": {"n": len(h_likely), "after": h4 + len(h_likely)},
            "ceiling_gap": 218 - h4,
        },
        "senate": {
            "start": s0,
            "persuade": {"names": SENATE_PERSUADE, "n": len(SENATE_PERSUADE), "after": s1},
            "special": {"after": s2},
            "primary": {"names": SENATE_PRIMARY, "n": len(SENATE_PRIMARY), "after": s3},
            "pickups": {"states": SENATE_PICKUPS_2028, "n": len(SENATE_PICKUPS_2028), "after": s4},
            "gap_50": 50 - s4,
            "left": len(s_left),
            "left_swing": sum(1 for m in s_left if m["n"] in SENATE_SWING),
            "up_2028": {"n": len(up("2028")), "supporters": sum(map(sup, up("2028"))),
                        "supporter_names": [m["n"] for m in up("2028") if sup(m)],
                        "others": [f'{m["n"]} ({m["st"]})' for m in up("2028") if not sup(m)]},
            "up_2030": {"n": len(up("2030")), "supporters": sum(map(sup, up("2030")))},
            "option_gap": 50 - senate["medicare_option"],
            "option_rest": {"n": len(s_opt_rest), "by_pos": dict(Counter(m["pos"] for m in s_opt_rest))},
            "to_60": 60 - senate["seated"],
        },
    }

    summary = {
        "as_of": AS_OF,
        "house": house,
        "senate": senate,
        "ladder": ladder,
        "path": path,
        "gains": {"total": GAINS_TOTAL, "supporters": len(GAINS_SUPPORTERS), "names": GAINS_SUPPORTERS,
                  "rate": round(gains_rate, 4)},
        "dates_found": sum(1 for m in out if m["dt"]),
        "rows_total": len(out),
        "excluded": [f'{m["d"]} {m["n"]}: {m["why"]}' for m in out if not m["counted"]],
        "source_tallies": {k: tallies[k] for k in ("house_voting_seated_likely", "house_supporters",
                                                    "senate_supporters", "senate_seated_caucus", "count_note")},
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "members.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"members: {len(out)} rows ({len(H)} House and {len(Sn)} Senate counted); dates on {summary['dates_found']}")
    print(f"House {house['supporters']} of {house['seated']}, gap {house['gap_218']}; all safe seats {after_safe}")
    print("ladder:", [(b["key"], b["n"], b["cum"]) for b in ladder])
    print(f"Senate {senate['supporters']} of {senate['seated']}; +{senate['other_states']} other states = "
          f"{senate['if_all_other_states']}; swing {senate['swing']}; Medicare option {senate['medicare_option']}")
    ph, ps = path["house"], path["senate"]
    print(f"path House {ph['start']} -> {ph['lapsed']['after']} -> {ph['near']['after']} -> "
          f"{ph['rest_safe']['after']} -> {ph['pickups']['after']} (+{ph['likely']['n']} likely = {ph['likely']['after']})")
    print(f"path Senate {ps['start']} -> {ps['persuade']['after']} -> {ps['special']['after']} -> "
          f"{ps['primary']['after']} -> {ps['pickups']['after']}; {ps['left']} left ({ps['left_swing']} swing); "
          f"2028 up {ps['up_2028']['n']} ({ps['up_2028']['supporters']} supporters)")


if __name__ == "__main__":
    main()
