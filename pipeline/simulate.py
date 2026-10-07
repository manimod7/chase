"""Generate SIMULATED T20 matches in the Cricsheet JSON layout.

Purpose: let the whole pipeline (ingest -> features -> train -> export -> site) run end to end
before real Cricsheet files are available. Teams are fictional on purpose, so nothing here can be
mistaken for real match data. To use real data, drop Cricsheet T20 JSON files into data/raw/real/
and run `python pipeline/run_all.py --data data/raw/real`.
"""
import argparse
import json
import math
import os
import random
from datetime import date, timedelta

TEAMS = [
    "Aurora Kings", "Basalt Titans", "Cobalt Rangers", "Dune Riders", "Ember Hawks", "Fjord Wolves",
    "Granite Lions", "Harbor Sharks", "Ivory Falcons", "Jade Panthers", "Kestrel XI", "Lagoon Stars",
    "Mesa Bulls", "Nimbus Royals", "Onyx Warriors", "Prairie Eagles",
]
VENUES = ["Northfield Oval", "Eastgate Park", "Harbour Ground", "Summit Stadium", "Riverside Arena"]


def ball_probs(bat_skill, bowl_skill, wkts, balls_faced, pressure):
    """Per-ball outcome probabilities. Skill is a small number around 0; pressure is >0 when the
    chasing side is behind the rate and pushes risk taking (more boundaries and more wickets)."""
    phase = 0 if balls_faced < 36 else (1 if balls_faced < 96 else 2)  # powerplay, middle, death
    edge = bat_skill - bowl_skill
    aggr = [1.05, 0.9, 1.35][phase] * (1 + 0.35 * max(-0.5, min(1.5, pressure)))
    wick = [0.030, 0.032, 0.050][phase] * (1 - 0.8 * edge) * (1 + 0.45 * max(0, pressure)) * (1 + 0.04 * wkts)
    wide = 0.032
    noball = 0.006
    six = 0.058 * aggr * (1 + 1.2 * edge) * (1 - 0.05 * wkts)
    four = 0.118 * aggr * (1 + 0.9 * edge) * (1 - 0.04 * wkts)
    two = 0.070
    three = 0.004
    one = 0.33 * (1 + 0.2 * edge)
    dot = 1.0 - (wick + wide + noball + six + four + two + three + one)
    dot = max(dot, 0.10)
    return {"w": wick, "wd": wide, "nb": noball, "6": six, "4": four, "2": two, "3": three, "1": one, "0": dot}


def draw(rng, probs):
    r = rng.random() * sum(probs.values())
    acc = 0.0
    for k, v in probs.items():
        acc += v
        if r <= acc:
            return k
    return "0"


def play_innings(rng, bat_name, bat_skill, bowl_skill, target):
    overs = []
    runs = wkts = legal = 0
    cur = []
    over_no = 0
    while legal < 120 and wkts < 10:
        balls_left = 120 - legal
        pressure = 0.0
        if target is not None:
            need = target - runs
            if need <= 0:
                break
            rrr = need / (balls_left / 6.0)
            crr = runs / max(1, legal) * 6
            pressure = (rrr - 7.8) / 6.0 if legal > 6 else 0.0
        probs = ball_probs(bat_skill, bowl_skill, wkts, legal, pressure)
        k = draw(rng, probs)
        d = {"batter": "B%d" % (wkts + 1), "bowler": "W%d" % (over_no % 5 + 1), "non_striker": "B%d" % (wkts + 2),
             "runs": {"batter": 0, "extras": 0, "total": 0}}
        is_legal = True
        if k == "wd":
            d["runs"] = {"batter": 0, "extras": 1, "total": 1}
            d["extras"] = {"wides": 1}
            runs += 1
            is_legal = False
        elif k == "nb":
            r = 1 + (4 if rng.random() < 0.1 else 0)
            d["runs"] = {"batter": r - 1, "extras": 1, "total": r}
            d["extras"] = {"noballs": 1}
            runs += r
            is_legal = False
        elif k == "w":
            d["wickets"] = [{"player_out": d["batter"], "kind": rng.choice(["caught", "bowled", "lbw", "caught", "run out"])}]
            wkts += 1
        else:
            r = int(k)
            d["runs"] = {"batter": r, "extras": 0, "total": r}
            runs += r
        cur.append(d)
        if is_legal:
            legal += 1
            if legal % 6 == 0:
                overs.append({"over": over_no, "deliveries": cur})
                cur = []
                over_no += 1
    if cur:
        overs.append({"over": over_no, "deliveries": cur})
    inn = {"team": bat_name, "overs": overs}
    if target is not None:
        inn["target"] = {"overs": 20, "runs": target}
    return inn, runs, wkts


def simulate_match(rng, a, b, skills, d):
    toss_winner = rng.choice([a, b])
    bat_first = toss_winner if rng.random() < 0.5 else (b if toss_winner == a else a)
    chase = b if bat_first == a else a
    home_bump = 0.0
    inn1, r1, _ = play_innings(rng, bat_first, skills[bat_first] + home_bump, skills[chase], None)
    inn2, r2, _ = play_innings(rng, chase, skills[chase], skills[bat_first], r1 + 1)
    if r2 >= r1 + 1:
        outcome = {"winner": chase, "by": {"wickets": 10 - sum(1 for o in inn2["overs"] for x in o["deliveries"] if "wickets" in x)}}
    elif r2 == r1:
        outcome = {"result": "tie"}
    else:
        outcome = {"winner": bat_first, "by": {"runs": r1 - r2}}
    return {
        "meta": {"data_version": "simulated-1", "simulated": True},
        "info": {
            "dates": [d.isoformat()], "teams": [a, b], "gender": "male", "match_type": "T20",
            "venue": rng.choice(VENUES), "outcome": outcome,
            "toss": {"winner": toss_winner, "decision": "bat" if toss_winner == bat_first else "field"},
            "event": {"name": "Simulated League"},
        },
        "innings": [inn1, inn2],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw/sim")
    ap.add_argument("--matches", type=int, default=2600)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)
    skills = {t: rng.uniform(-0.08, 0.08) for t in TEAMS}
    start = date(2015, 1, 10)
    span = (date(2025, 12, 20) - start).days
    for i in range(args.matches):
        d = start + timedelta(days=int(i * span / args.matches))
        # skills drift a little over time
        if i % 120 == 0:
            for t in TEAMS:
                skills[t] = max(-0.11, min(0.11, skills[t] + rng.gauss(0, 0.012)))
        a, b = rng.sample(TEAMS, 2)
        m = simulate_match(rng, a, b, skills, d)
        with open(os.path.join(args.out, "%05d.json" % (i + 1)), "w") as f:
            json.dump(m, f, separators=(",", ":"))
    print("wrote", args.matches, "simulated matches to", args.out)


if __name__ == "__main__":
    main()
