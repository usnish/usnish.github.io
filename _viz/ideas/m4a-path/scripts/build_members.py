"""Build members.csv and tallies.json from members.json.

Run from anywhere:  python3 -I /Users/usnish/code/usnish.github.io/_viz/ideas/m4a-path/scripts/build_members.py
Reads ../members.json, writes ../members.csv and ../tallies.json, prints the tallies.
"""
import csv
import json
import pathlib
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "members.json"
CSV_OUT = ROOT / "members.csv"
TALLY_OUT = ROOT / "tallies.json"

COLS = ["name", "chamber", "state", "district", "status", "m4a_119", "position",
        "past_cosponsor", "confidence", "margin_2026", "seat_rating", "next_election",
        "quote", "source_url", "website", "note"]

SUPPORT = {"cosponsor_119", "supports_m4a"}
NONVOTING = {"DC", "PR", "VI", "GU"}

# Rows that may not be seated (trailing, runoff, or not a Democrat).
# Leaders in uncalled races are kept; trailing candidates are not.
NOT_SEATED = {
    ("House", "NC-7"),   # Hardy trails
    ("House", "CA-23"),  # Hodge trails
    ("House", "AK-AL"),  # Bill Hill trails, and is an independent
    ("House", "LA-5"),   # Dec 12 runoff
    ("House", "LA-6"),   # Dec 12 runoff
}
# CA-4 is D-vs-D: count the seat once. Jones leads, so Jones counts as the seated member.
CA4_SKIP = ("House", "CA-4", "Mike Thompson")


def build_note(r):
    parts = []
    party = (r.get("party") or "").strip()
    if party and party != "D":
        parts.append(f"Party: {party}.")
    if r.get("note"):
        parts.append(r["note"].strip())
    if r.get("pos_note"):
        parts.append("Position note: " + r["pos_note"].strip())
    return " ".join(parts)


def main():
    rows = json.loads(SRC.read_text(encoding="utf-8"))

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows:
            out = {c: r.get(c, "") for c in COLS if c != "note"}
            out["note"] = build_note(r)
            w.writerow(out)

    t = {"rows_total": len(rows)}
    t["rows_by_chamber"] = dict(Counter(r["chamber"] for r in rows))
    t["rows_by_status"] = {ch: dict(Counter(r["status"] for r in rows if r["chamber"] == ch))
                           for ch in ("House", "Senate")}

    def seated(r):
        key = (r["chamber"], r["district"])
        if r["chamber"] == "House" and key in NOT_SEATED:
            return False
        if (r["chamber"], r["district"], r["name"]) == CA4_SKIP:
            return False
        return True

    house_all = [r for r in rows if r["chamber"] == "House"]
    house_vote = [r for r in house_all if r["state"] not in NONVOTING and seated(r)]
    house_nonvoting = [r for r in house_all if r["state"] in NONVOTING]
    senate = [r for r in rows if r["chamber"] == "Senate"]
    senate_seated_likely = [r for r in senate if r["name"] != "Mary Peltola"]

    t["house_voting_seated_likely"] = len(house_vote)
    t["house_excluded_rows"] = sorted(
        f'{r["district"]} {r["name"]}' for r in house_all
        if r["state"] not in NONVOTING and not seated(r))
    t["house_nonvoting_rows"] = [f'{r["district"]} {r["name"]}' for r in house_nonvoting]
    t["house_position"] = dict(Counter(r["position"] for r in house_vote))
    t["house_supporters"] = sum(r["position"] in SUPPORT for r in house_vote)
    t["house_cosponsor_119_returning"] = sum(r["position"] == "cosponsor_119" for r in house_vote)
    t["house_supports_m4a_new"] = sum(r["position"] == "supports_m4a" for r in house_vote)
    t["house_supports_single_payer_in_principle"] = sum(
        r["position"] == "supports_single_payer_in_principle" for r in house_vote)
    t["house_rating"] = dict(Counter(r["seat_rating"] for r in house_vote))
    t["house_nonsupporter_by_rating"] = dict(Counter(
        r["seat_rating"] for r in house_vote if r["position"] not in SUPPORT))
    t["house_nonsupporter_safe_by_position"] = dict(Counter(
        r["position"] for r in house_vote
        if r["position"] not in SUPPORT and r["seat_rating"] == "safe"))
    t["house_supporter_by_rating"] = dict(Counter(
        r["seat_rating"] for r in house_vote if r["position"] in SUPPORT))
    t["house_uncalled_leaders_counted"] = sorted(
        f'{r["district"]} {r["name"]} ({r["position"]})'
        for r in house_vote if r["status"] == "uncalled")
    t["house_status"] = dict(Counter(r["status"] for r in house_vote))
    t["house_confidence_nonsupporters"] = dict(Counter(
        r["confidence"] for r in house_vote if r["position"] not in SUPPORT))
    t["house_dropped_off_past_cosponsor"] = sorted(
        f'{r["district"]} {r["name"]}' for r in house_vote
        if r["position"] not in SUPPORT
        and r.get("past_cosponsor", "").lower().startswith(("yes", "cosponsored", "h.r.676"))
    )

    t["senate_rows"] = len(senate)
    t["senate_position"] = dict(Counter(r["position"] for r in senate))
    t["senate_supporters_incl_peltola_row"] = sum(r["position"] in SUPPORT for r in senate)
    t["senate_supporters"] = sum(r["position"] in SUPPORT for r in senate_seated_likely)
    t["senate_cosponsor_119"] = sum(r["position"] == "cosponsor_119" for r in senate)
    t["senate_supports_m4a_new"] = sorted(r["name"] for r in senate if r["position"] == "supports_m4a")
    t["senate_po_or_buyin"] = sorted(r["name"] for r in senate
                                     if r["position"] in ("public_option", "lower_medicare_age_or_buy_in"))
    t["senate_opposes"] = sorted(r["name"] for r in senate if r["position"] == "opposes_m4a")
    # Seated only (Peltola's Alaska race is uncalled); she would add 1 to 2032.
    t["senate_by_next_election"] = dict(Counter(r["next_election"] for r in senate_seated_likely))
    t["senate_seated_caucus"] = len(senate_seated_likely)
    t["senate_pending_rows"] = [r["name"] for r in senate if r["name"] == "Mary Peltola"]
    # The "cosponsor_119" position includes each bill's sponsor (Sanders, Jayapal).
    t["count_note"] = ("senate_cosponsor_119 and house_cosponsor_119_returning count sponsor OR cosponsor: "
                       "Senate = 17 returning S.1506 cosponsors + Sanders (Tina Smith retires); "
                       "House = 94 returning H.R.3069 cosponsors + Jayapal in seated seats "
                       "(CA-4 Mike Thompson, trailing, excluded).")
    t["house_sponsor_or_cosponsor_rows_incl_excluded"] = sum(
        r["position"] == "cosponsor_119" for r in house_all)
    t["senate_nonsupporters_up_2028"] = sorted(
        f'{r["state"]} {r["name"]} ({r["position"]})' for r in senate
        if r["position"] not in SUPPORT and r["next_election"] == "2028")
    t["senate_nonsupporters_up_2030"] = sorted(
        f'{r["state"]} {r["name"]} ({r["position"]})' for r in senate
        if r["position"] not in SUPPORT and r["next_election"] == "2030")

    TALLY_OUT.write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(t, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
