# Chase: ball-by-ball win probability for T20 cricket

**Live demo:** https://manimod7.github.io/chase/ · **Source:** https://github.com/manimod7/chase · **Portfolio:** https://manimod7.github.io/

Pick an IPL match, replay it ball by ball, and watch the batting side's chance of winning move after every delivery. Each big swing comes with a plain-language reason. You can also describe any match situation yourself (score, wickets, balls left) and get a probability back.

Chase is for understanding matches. It is not for betting.

---

## Contents

1. [What it is](#what-it-is)
2. [Why I built it](#why-i-built-it)
3. [Try it](#try-it)
4. [Results, honestly](#results-honestly)
5. [How it works](#how-it-works)
6. [Repository layout](#repository-layout)
7. [Run it locally](#run-it-locally)
8. [The API](#the-api)
9. [Deployment](#deployment)
10. [Testing](#testing)
11. [FAQ](#faq)
12. [Data, credits and licence](#data-credits-and-licence)

## What it is

A win-probability model for T20 cricket, plus the app around it:

- **Replay** any of 119 held-out IPL matches ball by ball, with the probability curve and the biggest swings explained.
- **What-if** panel: set the innings, runs, wickets and balls left and read off the probability.
- **Model quality** tab: calibration (reliability) chart, accuracy by stage of the innings, and a comparison against simpler baselines.
- **Live scoring** API: create a session, post each ball, get the probability back. Available when the optional backend is running.

The hosted demo runs entirely in your browser. There is no server: the trained model is shipped as JSON and evaluated by `engine.js`.

## Why I built it

I wanted a real end-to-end machine-learning project that I could defend line by line: real data, a leakage-free evaluation, a model that respects cricket logic, honest numbers, and a product someone can actually open. Win probability is a good fit because it is easy to explain, easy to sanity-check against intuition, and easy to get subtly wrong (random splits that leak future matches, uncalibrated probabilities, models that say a wicket helps the batting side).

## Try it

Open https://manimod7.github.io/chase/ and pick a match. Use the arrow keys or the slider to step through the innings. The light/dark toggle is in the top right.

## Results, honestly

Evaluated on the **119 most recent matches (28,889 ball states)** that the model never saw. Lower is better for Brier score, log loss and ECE.

| Model | Brier | Log loss | ECE |
| --- | --- | --- | --- |
| **Chase (LightGBM, monotone, calibrated)** | **0.1914** | 0.5538 | 0.0504 |
| Chase before calibration | 0.1911 | 0.5534 | 0.0469 |
| Logistic regression baseline | 0.1899 | 0.5488 | 0.0454 |
| Prior only (always 50%) | 0.2500 | 0.6931 | 0.0101 |

- **Chase is level with a plain logistic regression**, not clearly better. On this data the extra model complexity buys cricket-sensible behaviour (guaranteed monotonicity), not extra accuracy. I report this rather than hide it.
- **Monotonicity violations: 0.** More wickets never help the batting side; more runs or more balls left never hurt it. This holds across the whole test set for `wkts`, `runs` and `balls_left`.
- **Calibration** is reasonable but not perfect: the reliability chart shows the model is somewhat optimistic in the 50 to 80 per cent bands.
- **By stage:** second-innings predictions get sharp quickly (Brier about 0.07 in overs 16 to 20) while first-innings predictions stay close to a coin flip, which is what you would expect.
- Team strength (an Elo-style prior) was tested at several settings and added nothing on IPL data, so it is held neutral (`ELO_K = 0`).

## How it works

1. **Ingest** (`pipeline/ingest.py`): each ball of each match becomes one row of match state (innings, runs, wickets, balls left, runs needed, required run rate, a resource measure, and the prior).
2. **Features** (`pipeline/features.py`): `inn, runs, wkts, balls_left, runs_needed, rrr, resource, prior_logit`, with a monotone constraint per feature (`[0, +1, -1, +1, -1, -1, +1, +1]`).
3. **Split by date, never at random:** about 80% oldest matches to train (948), the next 10% to calibrate (118), the latest 10% to test (119). This stops the model learning from the future.
4. **Train** (`pipeline/train.py`): LightGBM with monotone constraints (the "advanced" method), L2 regularisation and bagging, early-stopped on the calibration slice.
5. **Calibrate:** Platt scaling (two parameters, smooth and monotone). Isotonic regression was rejected because it is step-shaped and can break monotonicity.
6. **Export:** the trees are written to `model.json`. `engine.js` evaluates them in the browser, and `backend/app/engine.py` evaluates the same trees in Python.
7. **Explain swings:** the largest probability changes between consecutive balls are listed with the event that caused them (wicket, boundary, expensive over).

### Same answer everywhere

The browser engine, the Python engine and LightGBM itself must agree. `tests/parity.py` and `tests/parity.js` check that predictions match to within 1e-6 on held-out matches, so what you see in the browser is exactly what the trained model says.

## Repository layout

```
docs/       the site as published on GitHub Pages (model, matches, calibration report in docs/data)
web/        the same site, source copy served by the API
index.html  redirects to docs/ so the root URL works on Pages
pipeline/   simulate.py  ingest.py  features.py  train.py  run_all.py
backend/    FastAPI service (app/), Lambda handler, tests
deploy/     aws_lambda.sh, gcp_cloud_run.sh
tests/      parity.py  parity.js  run_tests.sh
data/       raw and processed data used by the pipeline
```

## Run it locally

```
pip install -r requirements.txt
pip install fastapi uvicorn httpx pytest

# Rebuild everything from real Cricsheet IPL files placed in data/raw/real/ipl_json/
python pipeline/run_all.py --data data/raw/real --source Cricsheet

# or run on simulated matches between fictional teams, as a smoke test
python pipeline/run_all.py --simulate

bash tests/run_tests.sh                 # parity and model checks
python -m pytest backend/tests -q       # API tests
uvicorn backend.app.main:app            # site and API at http://localhost:8000
```

To just view the site with no backend, open `docs/index.html` through any static server (for example `python3 -m http.server` inside `docs/`).

## The API

Interactive docs at `/docs` when the server is running.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | status and model info |
| `GET /api/matches` | list of matches |
| `GET /api/matches/{id}/timeline` | win probability after every ball, plus the biggest swings with reasons |
| `POST /api/predict` | probability for any situation you describe |
| `GET /api/replay/{id}/stream` | server-sent events replaying a match ball by ball |
| `POST /api/live`, `POST /api/live/{id}/ball`, `POST /api/live/{id}/innings`, `GET /api/live/{id}/stream` | score a match live and get the probability after each ball |
| `GET /api/calibration` | the model-quality report |

Live sessions are kept in memory, so run a single instance.

## Deployment

**Hosted demo (GitHub Pages).** Settings, Pages, deploy from branch `main`, folder `/` (the root `index.html` forwards to `docs/`). With `window.CHASE_CONFIG = { api: "" }` in `docs/config.js`, the site uses the in-browser model and needs no backend.

**Optional API on AWS Lambda.** `bash deploy/aws_lambda.sh` (needs AWS CLI v2 and credentials; region defaults to ap-south-1). It prints a Function URL; put it in `docs/config.js` as `api`. Lambda does not stream, so the two SSE endpoints return when finished, and live sessions reset on a cold start. This is **not deployed** for the public demo.

**Optional API on Google Cloud Run.** `bash deploy/gcp_cloud_run.sh` (needs gcloud and a project with billing enabled). It uses `--max-instances=1` because live sessions are in memory.

## Testing

- `tests/parity.py` and `tests/parity.js`: browser, Python and LightGBM predictions agree to 1e-6.
- Monotonicity checks over the whole test set (reported in the model-quality tab).
- `backend/tests`: API behaviour with pytest.

## FAQ

**Is this a betting tool?** No, and it should not be used as one. It estimates probabilities from past IPL matches and has a Brier score of about 0.19.

**Does it work for other formats or leagues?** It is trained on IPL data only. T20 internationals or other leagues would need retraining and a fresh evaluation.

**Why not a bigger model?** On this data a logistic regression scores about the same. A constrained gradient-boosted model was chosen because it can be forced to obey cricket logic and can model non-linear effects like the end of an innings.

**Why does the first innings look so uncertain?** Because it is. Early in a first innings the outcome is close to a coin flip and the model says so.

**Why is Platt scaling used instead of isotonic?** It keeps the output smooth and monotone.

**Why a date split?** A random split would put balls from the same match, or later matches, in both training and test sets and inflate the scores.

**Does the model know the teams or players?** No. It sees only the match situation. A team-strength prior was tested and gave no improvement.

**Where does the data come from?** Cricsheet, see below.

**Why does the demo not need a server?** The trained trees are small JSON and `engine.js` evaluates them in the browser, verified against Python by the parity tests.

**What is not done?** The AWS API is not deployed, and the model has no knowledge of pitch, weather, toss, or player form.

## Data, credits and licence

Ball-by-ball data is from **Cricsheet** (https://cricsheet.org), IPL matches. Please check Cricsheet's terms before republishing derived data, and keep the credit on the site. Code is by Manish Modwani.

Built with Python, pandas, LightGBM, scikit-learn, FastAPI, Mangum (for Lambda), and plain HTML, CSS and JavaScript.
