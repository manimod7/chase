"""Read Cricsheet-format match JSON, compute the Elo prior chronologically, and write one row per
delivery (plus the starting state of each innings) to Parquet, and a compact per-match record."""
import argparse
import glob
import json
import os

import pandas as pd

from features import ELO_START, FEATURES, elo_update, prior_logit, state_features


ALIASES = {
    "Delhi Daredevils": "Delhi Capitals", "Kings XI Punjab": "Punjab Kings",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru", "Rising Pune Supergiants": "Rising Pune Supergiant",
    "Deccan Chargers": "Sunrisers Hyderabad", "Gujarat Lions": "Gujarat Titans",
}


def canon(n):
    return ALIASES.get(n, n)


def usable(m):
    """Keep full 20-over matches with a clean winner: no DLS/reduced overs, ties or no results."""
    info = m.get("info", {})
    oc = info.get("outcome", {})
    if "winner" not in oc or oc.get("method") or oc.get("result") or "eliminator" in oc or "bowl_out" in oc:
        return False
    if info.get("overs", 20) != 20 or len(m.get("innings", [])) != 2:
        return False
    if any(i.get("super_over") for i in m["innings"]):
        return False
    t = m["innings"][1].get("target", {})
    return t.get("overs", 20) == 20


def load_matches(path):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True)):
        try:
            m = json.load(open(f))
        except Exception:
            continue
        info = m.get("info", {})
        if info.get("match_type") != "T20" or info.get("gender", "male") != "male":
            continue
        if not usable(m):
            continue
        info["teams"] = [canon(t) for t in info["teams"]]
        for i in m["innings"]:
            i["team"] = canon(i["team"])
        if "winner" in info.get("outcome", {}):
            info["outcome"]["winner"] = canon(info["outcome"]["winner"])
        out.append((os.path.splitext(os.path.basename(f))[0], m))
    out.sort(key=lambda x: (x[1]["info"]["dates"][0], x[0]))
    return out


def parse_innings(inn):
    """Yield compact balls: (legal, total, wicket, batter_runs, extra_kind)."""
    balls = []
    for ov in inn.get("overs", []):
        for d in ov["deliveries"]:
            ex = d.get("extras", {})
            legal = 0 if ("wides" in ex or "noballs" in ex) else 1
            kind = 1 if "wides" in ex else 2 if "noballs" in ex else 3 if ex else 0
            wk = 1 if d.get("wickets") else 0
            balls.append((legal, d["runs"]["total"], wk, d["runs"]["batter"], kind))
    return balls


def build(matches):
    rows, records = [], []
    elo = {}
    for mid, m in matches:
        info = m["info"]
        winner = info.get("outcome", {}).get("winner")
        a, b = info["teams"]
        ra, rb = elo.get(a, ELO_START), elo.get(b, ELO_START)
        innings = m.get("innings", [])
        if winner is None or len(innings) < 2:
            continue
        parsed = [parse_innings(i) for i in innings[:2]]
        target = None
        if "target" in innings[1]:
            target = innings[1]["target"]["runs"]
        else:
            target = sum(x[1] for x in parsed[0]) + 1
        date = info["dates"][0]
        recs = []
        for k in range(2):
            team = innings[k]["team"]
            opp = b if team == a else a
            elo_bat, elo_bowl = (ra, rb) if team == a else (rb, ra)
            pl = prior_logit(elo_bat, elo_bowl)
            label = 1 if winner == team else 0
            runs = wkts = legal = 0
            tgt = target if k == 1 else None

            def emit(ball_idx):
                f = state_features(k + 1, runs, wkts, legal, tgt, pl)
                rows.append([mid, date, ball_idx] + f + [label])

            emit(0)
            for i, (lg, tot, wk, br, kind) in enumerate(parsed[k]):
                runs += tot
                wkts += wk
                legal += lg
                emit(i + 1)
            recs.append({"team": team, "target": tgt, "balls": [list(x) for x in parsed[k]]})
        records.append({
            "id": mid, "date": date, "teams": [a, b], "venue": info.get("venue", ""),
            "toss": info.get("toss", {}), "winner": winner, "outcome": info.get("outcome", {}),
            "elo": {a: ra, b: rb}, "innings": recs,
        })
        a_won = winner == a
        elo[a], elo[b] = elo_update(ra, rb, a_won)
    df = pd.DataFrame(rows, columns=["match_id", "date", "ball_idx"] + FEATURES + ["label"])
    return df, records, elo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw/sim")
    ap.add_argument("--out", default="data/processed")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    matches = load_matches(args.data)
    df, records, elo = build(matches)
    df.to_parquet(os.path.join(args.out, "ball_states.parquet"), index=False)
    json.dump(records, open(os.path.join(args.out, "matches.json"), "w"), separators=(",", ":"))
    print("matches:", len(records), "ball-state rows:", len(df))


if __name__ == "__main__":
    main()
