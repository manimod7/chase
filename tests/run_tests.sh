#!/usr/bin/env bash
# Run from the repository root: bash tests/run_tests.sh
set -e
python3 tests/parity.py   # browser engine reproduces the Python model, ball for ball
python3 - <<'PY'
import json
r = json.load(open("web/data/calibration.json"))
m = r["monotonicity"]
assert all(v["violation_rate"] == 0 for v in m.values()), m
c = r["models"]["chase_calibrated"]
assert c["ece"] < 0.06, c["ece"]
assert c["brier"] < r["models"]["prior_only"]["brier"]
assert c["brier"] < 0.21, c["brier"]
print("model checks passed: monotone, calibration error", round(c["ece"], 4))
PY
