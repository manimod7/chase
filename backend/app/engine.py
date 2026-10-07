"""Win-probability engine: evaluates the exported tree model in pure Python.

It reads the same model.json the browser uses, so the API and the site cannot disagree.
backend/tests/test_parity.py checks it against LightGBM itself and against the training features.
"""
import json
import math
from pathlib import Path

LN10_OVER_400 = math.log(10) / 400.0


def prior_logit(elo_bat, elo_bowl):
    return (elo_bat - elo_bowl) * LN10_OVER_400


def state_features(inn, runs, wkts, legal, target, prior):
    """Must match pipeline/features.py::state_features exactly (a test enforces it)."""
    balls_left = 120 - legal
    runs_needed = 0.0
    rrr = 0.0
    if inn == 2 and target is not None:
        need = target - runs
        if need <= 0:
            rrr = 0.0
        elif balls_left <= 0:
            rrr = 99.0
        else:
            rrr = need / balls_left * 6.0
        runs_needed = float(max(need, 0))
    resource = balls_left * (10 - wkts) / 1200.0
    return [float(inn), float(runs), float(wkts), float(balls_left), runs_needed, rrr, resource, prior]


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


def _eval_tree(node, x):
    while not isinstance(node, (int, float)):
        node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
    return node


class Model:
    def __init__(self, path):
        raw = json.loads(Path(path).read_text())
        self.trees = raw["trees"]
        self.a = raw["platt"]["a"]
        self.b = raw["platt"]["b"]
        self.source = raw.get("source", "unknown")
        self.features = raw["features"]

    def raw_score(self, x):
        return sum(_eval_tree(t, x) for t in self.trees)

    def predict(self, x):
        """Probability that the batting side wins."""
        return _sigmoid(self.a * self.raw_score(x) + self.b)


# ---------- timelines and explanations ----------

def timeline(model, match):
    """One point per delivery plus each innings' starting state; pA is the win probability of teams[0]."""
    a_team = match["teams"][0]
    first_runs = sum(b[1] for b in match["innings"][0]["balls"])
    pts = []
    for k in range(2):
        inn = match["innings"][k]
        team = inn["team"]
        other = match["teams"][1] if team == a_team else a_team
        pl = prior_logit(match["elo"][team], match["elo"][other])
        tgt = (inn.get("target") or first_runs + 1) if k == 1 else None
        runs = wkts = legal = 0
        for i in range(len(inn["balls"]) + 1):
            ball = None
            if i > 0:
                ball = inn["balls"][i - 1]
                legal += ball[0]
                runs += ball[1]
                wkts += ball[2]
            p_bat = model.predict(state_features(k + 1, runs, wkts, legal, tgt, pl))
            pts.append({"inn": k + 1, "i": i, "runs": runs, "wkts": wkts, "legal": legal, "target": tgt,
                        "bat": team, "pA": p_bat if team == a_team else 1.0 - p_bat, "ball": ball})
    return pts


def event_label(ball):
    if ball is None:
        return "Start of innings"
    legal, total, wicket, bat_runs, kind = ball
    if wicket:
        return "Wicket"
    if kind == 1:
        return "Wide"
    if kind == 2:
        return "No ball"
    if bat_runs == 6:
        return "Six"
    if bat_runs == 4:
        return "Four"
    if total == 0:
        return "Dot ball"
    return f"{total} run" + ("" if total == 1 else "s")


def overs(legal):
    return f"{legal // 6}.{legal % 6}"


def state_text(p):
    if p["inn"] == 1:
        return f"{p['bat']} {p['runs']}/{p['wkts']} after {overs(p['legal'])} overs"
    need = p["target"] - p["runs"]
    left = 120 - p["legal"]
    if need <= 0:
        return f"{p['bat']} {p['runs']}/{p['wkts']}, target reached"
    return f"{p['bat']} {p['runs']}/{p['wkts']}, need {need} off {left} ball" + ("" if left == 1 else "s")


def swing(prev, cur, teams):
    """Describe how one ball moved the probability, or None when it moved less than 5 points."""
    if prev is None or prev["inn"] != cur["inn"]:
        return None
    d = cur["pA"] - prev["pA"]
    if abs(d) < 0.05:
        return None
    return {"i": cur["i"] if cur["inn"] == 1 else None, "delta": d, "favours": teams[0] if d > 0 else teams[1],
            "event": event_label(cur["ball"]), "state": state_text(cur), "over": overs(cur["legal"]), "inn": cur["inn"]}


def top_swings(pts, teams, limit=12):
    out = []
    for idx in range(1, len(pts)):
        s = swing(pts[idx - 1], pts[idx], teams)
        if s:
            s["i"] = idx  # index into the full two-innings timeline
            out.append(s)
    out.sort(key=lambda s: -abs(s["delta"]))
    return sorted(out[:limit], key=lambda s: s["i"])
