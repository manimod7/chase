# Chase: ball-by-ball win probability for T20 cricket

Pick a match, replay it ball by ball, and watch the win probability move, with a reason for each big swing.
A FastAPI service computes the predictions and a static site calls it. With no API reachable, the site falls back to running the same model in the browser.

**Data note.** This build ships with *simulated matches between fictional teams* so the whole pipeline runs
end to end. To use real ball-by-ball data, download Cricsheet T20 JSON files, unzip them into `data/raw/real/`, and run:

    python pipeline/run_all.py --data data/raw/real --source Cricsheet

Check Cricsheet's terms before publishing derived data, and keep the credit on the site.

## Layout

    backend/    FastAPI service (app/), tests/, Dockerfile
    deploy/     aws_lambda.sh, gcp_cloud_run.sh
    pipeline/   simulate.py  ingest.py  features.py  train.py  run_all.py
    web/        index.html  styles.css  engine.js  app.js  data/ (model, matches, calibration report)
    tests/      parity.py  parity.js  run_tests.sh
    docs/       the same site, ready for GitHub Pages ("main" branch, "/docs" folder)

## Run

    pip install -r requirements.txt
    pip install fastapi uvicorn httpx pytest
    python pipeline/run_all.py --simulate      # build data, train, evaluate, export
    bash tests/run_tests.sh                     # parity and model checks
    python -m pytest backend/tests -q           # API tests
    uvicorn backend.app.main:app                # site and API at http://localhost:8000

## How it works

1. `ingest.py` turns each ball into a state row and builds a pre-match Elo prior from earlier results only.
2. `train.py` fits a LightGBM model with monotone constraints (more wickets never help the batting side; more runs
   or balls never hurt), recalibrates it with Platt scaling on a later slice of matches, and scores it on the latest
   matches. Splits are by date, never random.
3. The trees are exported to JSON and evaluated by `web/engine.js`. `tests/parity.py` checks the browser output matches
   Python to within 1e-6 on held-out matches.

## The API

    uvicorn backend.app.main:app --reload       # http://localhost:8000/docs for interactive docs

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | status and model info |
| `GET /api/matches` | list of matches |
| `GET /api/matches/{id}/timeline` | win probability after every ball, plus the biggest swings with reasons |
| `POST /api/predict` | probability for any situation you describe |
| `GET /api/replay/{id}/stream` | server-sent events replaying a match ball by ball |
| `POST /api/live`, `POST /api/live/{id}/ball`, `POST /api/live/{id}/innings`, `GET /api/live/{id}/stream` | score a match live and get the probability after each ball |
| `GET /api/calibration` | the model-quality report |

Live sessions live in memory, so run one instance (the deploy script sets `--max-instances=1`).

## Deploy the API to AWS Lambda (free tier)

1. Install and sign in to the AWS CLI v2 (`aws configure` or `aws sso login`).
2. From the repository root run `bash deploy/aws_lambda.sh` (region defaults to ap-south-1; override with `AWS_REGION`).
3. It prints an HTTPS Function URL. Put it in `docs/config.js` as `api`.
Notes: Lambda does not stream, so the two SSE endpoints return after finishing; the site uses plain requests and is unaffected. Live-scoring sessions live in memory and reset on a cold start.

## Alternative: Google Cloud Run (free tier)

1. Install the gcloud CLI, then `gcloud auth login` and `gcloud config set project YOUR_PROJECT_ID` (billing must be enabled on the project; Cloud Run's free quota still applies).
2. From the repository root run `bash deploy/gcp_cloud_run.sh`.
3. It prints a URL such as `https://chase-xxxxx-el.a.run.app`. Open it: the API serves the site too.

## Optional: host the site on GitHub Pages and point it at the API

0. Put your Cloud Run URL in `docs/config.js` (`api: "https://chase-xxxxx-el.a.run.app"`).
1. Create a public repo (for example `chase`) and push this folder to `main`.
2. Settings, Pages, Source "Deploy from a branch", branch `main`, folder `/docs`.
3. The site goes live at `https://<your-username>.github.io/chase/`.

Chase is for understanding matches, not for betting.
