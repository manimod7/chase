"""Shared definitions: ball-state features and Elo prior. The browser engine (web/engine.js) mirrors
these exactly; tests/parity.py checks that both give the same probabilities."""
import math

FEATURES = ["inn", "runs", "wkts", "balls_left", "runs_needed", "rrr", "resource", "prior_logit"]
# +1: probability of the batting side winning must not fall as the feature rises; -1 the reverse.
MONOTONE = [0, 1, -1, 1, -1, -1, 1, 1]

ELO_START = 1500.0
ELO_K = 0.0  # ratings add nothing on IPL data (tested K=0..12); kept at 0 so the prior is neutral
LN10_OVER_400 = math.log(10) / 400.0


def prior_logit(elo_bat, elo_bowl):
    return (elo_bat - elo_bowl) * LN10_OVER_400


def state_features(inn, runs, wkts, legal, target, prior):
    """Features for the state after a delivery. `legal` = legal balls bowled, `target` = runs to
    win in innings 2 (None in innings 1)."""
    balls_left = 120 - legal
    if inn == 2 and target is not None:
        need = target - runs
        if need <= 0:
            rrr = 0.0
        elif balls_left <= 0:
            rrr = 99.0
        else:
            rrr = need / balls_left * 6.0
        runs_needed = float(max(need, 0))
    else:
        runs_needed = 0.0
        rrr = 0.0
    # Batting resources left, a smooth stand-in for 'balls and wickets in hand' (0 to 1).
    resource = balls_left * (10 - wkts) / 1200.0
    return [float(inn), float(runs), float(wkts), float(balls_left), runs_needed, rrr, resource, prior]


def elo_update(ra, rb, a_won):
    ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
    sa = 1.0 if a_won else 0.0
    return ra + ELO_K * (sa - ea), rb + ELO_K * ((1 - sa) - (1 - ea))
