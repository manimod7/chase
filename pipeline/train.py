"""Train a monotone LightGBM win-probability model, calibrate it with Platt scaling on a
later slice of matches, evaluate on the latest matches, and export everything the site needs."""
import argparse
import json
import math
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from features import FEATURES, MONOTONE


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability(p, y, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    out, ece = [], 0.0
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        if m.sum() == 0:
            continue
        out.append({"lo": float(edges[i]), "hi": float(edges[i + 1]), "pred": float(p[m].mean()),
                    "actual": float(y[m].mean()), "n": int(m.sum())})
        ece += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return out, float(ece)


def metrics(p, y):
    rel, ece = reliability(p, y)
    return {"brier": brier(p, y), "logloss": logloss(p, y), "ece": ece, "reliability": rel}


def flatten_tree(node):
    if "leaf_value" in node:
        return node["leaf_value"]
    assert node["decision_type"] == "<="
    return {"f": node["split_feature"], "t": node["threshold"], "d": 1 if node.get("default_left", True) else 0,
            "l": flatten_tree(node["left_child"]), "r": flatten_tree(node["right_child"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", default="data/processed")
    ap.add_argument("--out", default="web/data")
    ap.add_argument("--source", default="simulated")
    ap.add_argument("--web-matches", type=int, default=120)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    df = pd.read_parquet(os.path.join(args.processed, "ball_states.parquet"))
    matches = json.load(open(os.path.join(args.processed, "matches.json")))
    order = sorted({(m["date"], m["id"]) for m in matches})
    ids = [i for _, i in order]
    n = len(ids)
    train_ids = set(ids[: int(n * 0.80)])
    calib_ids = set(ids[int(n * 0.80): int(n * 0.90)])
    test_ids = set(ids[int(n * 0.90):])
    tr = df[df.match_id.isin(train_ids)]
    ca = df[df.match_id.isin(calib_ids)]
    te = df[df.match_id.isin(test_ids)]
    print("matches train/calib/test:", len(train_ids), len(calib_ids), len(test_ids))

    params = dict(objective="binary", learning_rate=0.03, num_leaves=4, min_data_in_leaf=800, feature_fraction=1.0,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=20.0, monotone_constraints=MONOTONE,
                  monotone_constraints_method="advanced", verbose=-1, seed=11)
    dtr = lgb.Dataset(tr[FEATURES].values, tr.label.values, feature_name=FEATURES)
    dca = lgb.Dataset(ca[FEATURES].values, ca.label.values, reference=dtr)
    booster = lgb.train(params, dtr, num_boost_round=1500, valid_sets=[dca],
                        callbacks=[lgb.early_stopping(40, verbose=False)])
    print("best iteration:", booster.best_iteration)

    raw_ca = booster.predict(ca[FEATURES].values, num_iteration=booster.best_iteration, raw_score=True)
    # Platt scaling: a smooth, monotone recalibration with two parameters. Isotonic regression was
    # tried first and overfit the calibration slice (it produced exact 0 and 1 probabilities).
    platt = LogisticRegression(C=1e6, max_iter=500).fit(raw_ca.reshape(-1, 1), ca.label.values)
    platt_a, platt_b = float(platt.coef_[0][0]), float(platt.intercept_[0])

    def predict(d):
        raw = booster.predict(d[FEATURES].values, num_iteration=booster.best_iteration, raw_score=True)
        return sigmoid(raw), sigmoid(platt_a * raw + platt_b)

    y = te.label.values
    p_raw, p_cal = predict(te)
    p_prior = sigmoid(te.prior_logit.values)
    # Baseline: plain logistic regression on the same features.
    sc = StandardScaler().fit(tr[FEATURES].values)
    lr = LogisticRegression(max_iter=300).fit(sc.transform(tr[FEATURES].values), tr.label.values)
    p_lr = lr.predict_proba(sc.transform(te[FEATURES].values))[:, 1]

    report = {"source": args.source, "split": {"train_matches": len(train_ids), "calibration_matches": len(calib_ids),
                                               "test_matches": len(test_ids), "test_rows": int(len(te))},
              "models": {"chase_calibrated": metrics(p_cal, y), "chase_uncalibrated": metrics(p_raw, y),
                         "logistic_baseline": metrics(p_lr, y), "prior_only": metrics(p_prior, y)}}
    # By stage: overs of the current innings.
    stages = {}
    balls_faced = 120 - te.balls_left.values
    for inn in (1, 2):
        for lo, hi, name in [(0, 30, "overs 1-5"), (30, 60, "overs 6-10"), (60, 90, "overs 11-15"), (90, 121, "overs 16-20")]:
            m = (te.inn.values == inn) & (balls_faced >= lo) & (balls_faced < hi)
            if m.sum() < 50:
                continue
            stages["innings %d, %s" % (inn, name)] = {
                "n": int(m.sum()),
                "chase": brier(p_cal[m], y[m]), "logistic": brier(p_lr[m], y[m]), "prior": brier(p_prior[m], y[m])}
    report["by_stage"] = stages
    for k, v in report["models"].items():
        print("%-20s brier %.4f logloss %.4f ece %.4f" % (k, v["brier"], v["logloss"], v["ece"]))

    # Monotonicity audit on the held-out rows: wickets, runs.
    audit = {}
    base = te.sample(min(len(te), 4000), random_state=3)
    for feat, direction in [("wkts", -1), ("runs", 1), ("balls_left", 1)]:
        d2 = base.copy()
        step = 1.0
        d2[feat] = d2[feat] + step
        if feat == "runs":
            d2["runs_needed"] = np.maximum(d2["runs_needed"] - step, 0)
        pa = predict(base)[1]
        pb = predict(d2)[1]
        viol = float(np.mean((pb - pa) * direction < -1e-9))
        audit[feat] = {"direction": direction, "violation_rate": viol}
    report["monotonicity"] = audit
    print("monotonicity", audit)

    booster.save_model(os.path.join(args.processed, "model.txt"), num_iteration=booster.best_iteration)
    # Export model.
    dump = booster.dump_model(num_iteration=booster.best_iteration)
    model = {"features": FEATURES, "trees": [flatten_tree(t["tree_structure"]) for t in dump["tree_info"]],
             "platt": {"a": platt_a, "b": platt_b},
             "source": args.source}
    json.dump(model, open(os.path.join(args.out, "model.json"), "w"), separators=(",", ":"))
    json.dump(report, open(os.path.join(args.out, "calibration.json"), "w"), indent=1)

    # Export held-out matches for the site.
    test_matches = [m for m in matches if m["id"] in test_ids]
    test_matches.sort(key=lambda m: m["date"], reverse=True)
    pick = test_matches[: args.web_matches]
    index = []
    mdir = os.path.join(args.out, "matches")
    os.makedirs(mdir, exist_ok=True)
    for f in os.listdir(mdir):
        os.remove(os.path.join(mdir, f))
    for m in pick:
        json.dump(m, open(os.path.join(mdir, m["id"] + ".json"), "w"), separators=(",", ":"))
        tot = [sum(b[1] for b in i["balls"]) for i in m["innings"]]
        index.append({"id": m["id"], "date": m["date"], "teams": m["teams"], "venue": m["venue"],
                      "winner": m["winner"], "outcome": m["outcome"], "scores": tot,
                      "batFirst": m["innings"][0]["team"]})
    json.dump({"source": args.source, "matches": index}, open(os.path.join(args.out, "index.json"), "w"),
              separators=(",", ":"))
    print("exported", len(pick), "matches; trees:", len(model["trees"]))


if __name__ == "__main__":
    main()
