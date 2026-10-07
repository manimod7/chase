import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
from backend.app.main import app, MODEL, INDEX  # noqa: E402
from backend.app import engine  # noqa: E402
import features as train_features  # noqa: E402

client = TestClient(app)
MID = INDEX["matches"][0]["id"]


def test_health():
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["trees"] > 0


def test_features_match_training_code():
    rng = np.random.default_rng(1)
    for _ in range(500):
        inn = int(rng.integers(1, 3)); wk = int(rng.integers(0, 11)); legal = int(rng.integers(0, 121))
        runs = int(rng.integers(0, 250)); tgt = int(rng.integers(60, 250)) if inn == 2 else None
        pl = float(rng.normal(0, 0.3))
        assert engine.state_features(inn, runs, wk, legal, tgt, pl) == train_features.state_features(inn, runs, wk, legal, tgt, pl)


def test_model_matches_lightgbm():
    lgb = pytest.importorskip("lightgbm")
    model_txt = ROOT / "data" / "processed" / "model.txt"
    if not model_txt.exists():
        pytest.skip("run the pipeline first")
    booster = lgb.Booster(model_file=str(model_txt))
    rng = np.random.default_rng(2)
    X = np.array([engine.state_features(2, int(rng.integers(0, 200)), int(rng.integers(0, 10)), int(rng.integers(0, 120)),
                                        int(rng.integers(80, 220)), float(rng.normal(0, .3))) for _ in range(300)])
    raw = booster.predict(X, raw_score=True)
    mine = np.array([MODEL.raw_score(list(x)) for x in X])
    assert np.max(np.abs(raw - mine)) < 1e-9


def test_timeline_and_swings():
    r = client.get(f"/api/matches/{MID}/timeline").json()
    pts = r["points"]
    assert 0 <= min(p["pA"] for p in pts) and max(p["pA"] for p in pts) <= 1
    winner_is_a = r["match"]["winner"] == r["match"]["teams"][0]
    last = pts[-1]["pA"]
    assert (last > 0.9) if winner_is_a else (last < 0.1), (winner_is_a, last)
    assert all(abs(s["delta"]) >= 0.05 for s in r["swings"]) and len(r["swings"]) <= 12


def test_unknown_match_404():
    assert client.get("/api/matches/nope/timeline").status_code == 404


def test_predict_monotone_in_wickets_and_runs():
    base = dict(innings=2, runs=90, wickets=3, balls_bowled=70, target=160)
    p0 = client.post("/api/predict", json=base).json()["batting_win_probability"]
    assert client.post("/api/predict", json={**base, "wickets": 4}).json()["batting_win_probability"] <= p0
    assert client.post("/api/predict", json={**base, "runs": 95}).json()["batting_win_probability"] >= p0


def test_predict_validation():
    assert client.post("/api/predict", json=dict(innings=2, runs=10, wickets=1, balls_bowled=10)).status_code == 422
    assert client.post("/api/predict", json=dict(innings=1, runs=10, wickets=11, balls_bowled=10)).status_code == 422


def test_live_session_flow():
    r = client.post("/api/live", json={"team_a": "Aurora", "team_b": "Basalt", "batting_first": "Aurora"})
    assert r.status_code == 201
    sid = r.json()["id"]
    for _ in range(6):
        e = client.post(f"/api/live/{sid}/ball", json={"total_runs": 1, "batter_runs": 1}).json()
    assert e["point"]["legal"] == 6 and e["point"]["runs"] == 6
    w = client.post(f"/api/live/{sid}/ball", json={"total_runs": 0, "wicket": True}).json()
    assert w["point"]["wkts"] == 1
    n = client.post(f"/api/live/{sid}/innings").json()
    assert n["point"]["inn"] == 2 and n["point"]["target"] == 7
    st = client.get(f"/api/live/{sid}").json()
    assert len(st["points"]) == 1 + 7 + 1
    assert client.post("/api/live", json={"team_a": "A", "team_b": "B", "batting_first": "C"}).status_code == 422


def test_replay_stream_emits_points():
    with client.stream("GET", f"/api/replay/{MID}/stream?delay_ms=0&start=0") as r:
        text = "".join(r.iter_text())
    assert text.startswith("event: match") and text.count("event: point") > 100 and "event: end" in text


def test_matches_and_calibration():
    assert len(client.get("/api/matches").json()["matches"]) > 10
    assert "models" in client.get("/api/calibration").json()
