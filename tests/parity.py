"""Check that the browser engine reproduces the Python model, ball for ball, on held-out matches."""
import json, os, subprocess, sys
import lightgbm as lgb
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from features import FEATURES

ROOT = os.path.join(os.path.dirname(__file__), "..")
df = pd.read_parquet(os.path.join(ROOT, "data/processed/ball_states.parquet"))
model = json.load(open(os.path.join(ROOT, "web/data/model.json")))
booster = lgb.Booster(model_file=os.path.join(ROOT, "data/processed/model.txt"))
ids = [f[:-5] for f in sorted(os.listdir(os.path.join(ROOT, "web/data/matches")))][:25]
out = {}
worst = 0.0
for mid in ids:
    d = df[df.match_id == mid]
    raw = booster.predict(d[FEATURES].values, raw_score=True)
    p = 1 / (1 + np.exp(-(model["platt"]["a"] * raw + model["platt"]["b"])))
    out[mid] = p.tolist()
json.dump(out, open("/tmp/py_probs.json", "w"))
res = subprocess.run(["node", os.path.join(ROOT, "tests/parity.js"), "/tmp/py_probs.json"], capture_output=True, text=True)
print(res.stdout, res.stderr)
sys.exit(res.returncode)
