"""Chase API: win probability for T20 cricket, as a service.

Run locally:  uvicorn backend.app.main:app --reload     (from the repository root)
Configure with environment variables:
  CHASE_DATA          folder holding model.json, index.json, calibration.json, matches/   (default web/data)
  CHASE_WEB           folder of static site files to serve at "/"                          (default web, if it exists)
  CHASE_CORS_ORIGINS  comma-separated allowed origins, or "*"                              (default "*")
Live sessions are held in memory, so run a single instance (Cloud Run: --max-instances=1).
"""
import asyncio
import json
import os
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("CHASE_DATA", ROOT / "web" / "data"))
WEB = Path(os.environ.get("CHASE_WEB", ROOT / "web"))

app = FastAPI(title="Chase API", version="1.0.0",
              description="Ball-by-ball win probability for T20 cricket, with reasons for big swings.")
origins = [o.strip() for o in os.environ.get("CHASE_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

MODEL = engine.Model(DATA / "model.json")
INDEX = json.loads((DATA / "index.json").read_text())
CALIBRATION = json.loads((DATA / "calibration.json").read_text())
KNOWN = {m["id"] for m in INDEX["matches"]}


@lru_cache(maxsize=256)
def load_match(match_id):
    if match_id not in KNOWN:
        raise HTTPException(404, f"No match with id {match_id}")
    return json.loads((DATA / "matches" / f"{match_id}.json").read_text())


def meta(m):
    return {"id": m["id"], "date": m["date"], "teams": m["teams"], "venue": m.get("venue", ""), "winner": m["winner"],
            "outcome": m.get("outcome", {}), "elo": m["elo"],
            "innings": [{"team": i["team"], "target": i.get("target")} for i in m["innings"]]}


def sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


# ---------- read-only endpoints ----------

@app.get("/health")
def health():
    return {"status": "ok", "source": MODEL.source, "trees": len(MODEL.trees), "matches": len(KNOWN)}


@app.get("/api/matches")
def matches():
    return INDEX


@app.get("/api/matches/{match_id}/timeline")
def match_timeline(match_id: str):
    m = load_match(match_id)
    pts = engine.timeline(MODEL, m)
    return {"match": meta(m), "points": pts, "swings": engine.top_swings(pts, m["teams"])}


@app.get("/api/calibration")
def calibration():
    return CALIBRATION


class PredictIn(BaseModel):
    innings: int = Field(2, ge=1, le=2, description="1 = batting first, 2 = chasing")
    runs: int = Field(..., ge=0, le=400)
    wickets: int = Field(..., ge=0, le=10)
    balls_bowled: int = Field(..., ge=0, le=120, description="legal balls bowled in this innings")
    target: Optional[int] = Field(None, ge=1, le=400, description="runs to win; required when innings = 2")
    rating_edge: float = Field(0.0, ge=-400, le=400, description="batting side's rating minus the bowling side's")


@app.post("/api/predict")
def predict(body: PredictIn):
    if body.innings == 2 and body.target is None:
        raise HTTPException(422, "target is required when innings is 2")
    x = engine.state_features(body.innings, body.runs, body.wickets, body.balls_bowled,
                              body.target if body.innings == 2 else None,
                              engine.prior_logit(1500 + body.rating_edge, 1500))
    p = MODEL.predict(x)
    return {"batting_win_probability": p, "bowling_win_probability": 1 - p, "features": dict(zip(MODEL.features, x))}


@app.get("/api/replay/{match_id}/stream")
async def replay_stream(match_id: str, delay_ms: int = Query(120, ge=0, le=2000), start: int = Query(0, ge=0)):
    """Server-sent events: replay a finished match ball by ball, as if it were live."""
    m = load_match(match_id)
    pts = engine.timeline(MODEL, m)
    teams = m["teams"]

    async def gen():
        yield sse("match", meta(m))
        for idx in range(start, len(pts)):
            s = engine.swing(pts[idx - 1] if idx else None, pts[idx], teams)
            yield sse("point", {"index": idx, "point": pts[idx], "swing": s})
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
        yield sse("end", {"result": m.get("outcome", {})})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- live sessions (feed balls in, get probabilities out) ----------

class LiveIn(BaseModel):
    team_a: str = Field(..., min_length=1, max_length=40)
    team_b: str = Field(..., min_length=1, max_length=40)
    batting_first: str
    rating_a: float = 1500.0
    rating_b: float = 1500.0


class BallIn(BaseModel):
    total_runs: int = Field(..., ge=0, le=12, description="all runs from the delivery, including extras")
    batter_runs: int = Field(0, ge=0, le=7)
    wicket: bool = False
    extra: int = Field(0, ge=0, le=3, description="0 none, 1 wide, 2 no ball, 3 byes or leg byes")


class LiveSession:
    MAX_AGE = 6 * 3600

    def __init__(self, sid, body: LiveIn):
        if body.batting_first not in (body.team_a, body.team_b):
            raise HTTPException(422, "batting_first must be team_a or team_b")
        self.id, self.created = sid, time.time()
        self.teams = [body.team_a, body.team_b]
        self.elo = {body.team_a: body.rating_a, body.team_b: body.rating_b}
        self.bat = body.batting_first
        self.inn, self.runs, self.wkts, self.legal = 1, 0, 0, 0
        self.first_total, self.target, self.finished = None, None, False
        self.pts, self.subs = [], set()
        self._record(None)

    def _other(self):
        return self.teams[1] if self.bat == self.teams[0] else self.teams[0]

    def _record(self, ball):
        pl = engine.prior_logit(self.elo[self.bat], self.elo[self._other()])
        p_bat = MODEL.predict(engine.state_features(self.inn, self.runs, self.wkts, self.legal,
                                                    self.target if self.inn == 2 else None, pl))
        pt = {"inn": self.inn, "i": self.legal, "runs": self.runs, "wkts": self.wkts, "legal": self.legal,
              "target": self.target, "bat": self.bat, "pA": p_bat if self.bat == self.teams[0] else 1 - p_bat, "ball": ball}
        prev = self.pts[-1] if self.pts else None
        self.pts.append(pt)
        s = engine.swing(prev, pt, self.teams)
        if s:
            s["i"] = len(self.pts) - 1
        return {"index": len(self.pts) - 1, "point": pt, "swing": s}

    def _publish(self, ev):
        for q in list(self.subs):
            q.put_nowait(ev)

    def add_ball(self, b: BallIn):
        if self.finished:
            raise HTTPException(409, "This match has finished.")
        legal = 0 if b.extra in (1, 2) else 1
        self.runs += b.total_runs
        self.wkts += 1 if b.wicket else 0
        self.legal += legal
        ev = self._record([legal, b.total_runs, 1 if b.wicket else 0, b.batter_runs, b.extra])
        over = self.wkts >= 10 or self.legal >= 120 or (self.inn == 2 and self.runs >= (self.target or 10 ** 9))
        if over and self.inn == 2:
            self.finished = True
            ev["finished"] = True
        elif over:
            ev["innings_over"] = True
        self._publish(ev)
        return ev

    def next_innings(self):
        if self.inn != 1:
            raise HTTPException(409, "The second innings is already under way.")
        self.first_total = self.runs
        self.target = self.runs + 1
        self.inn, self.runs, self.wkts, self.legal = 2, 0, 0, 0
        self.bat = self._other()
        ev = self._record(None)
        self._publish(ev)
        return ev


SESSIONS = {}


def _sweep():
    now = time.time()
    for sid in [s for s, v in SESSIONS.items() if now - v.created > LiveSession.MAX_AGE]:
        SESSIONS.pop(sid, None)


def _get(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "Unknown live session")
    return s


@app.post("/api/live", status_code=201)
def live_create(body: LiveIn):
    _sweep()
    if len(SESSIONS) >= 200:
        raise HTTPException(429, "Too many live sessions; try again later.")
    sid = uuid.uuid4().hex[:10]
    SESSIONS[sid] = LiveSession(sid, body)
    s = SESSIONS[sid]
    return {"id": sid, "teams": s.teams, "batting": s.bat, "point": s.pts[0]}


@app.post("/api/live/{sid}/ball")
def live_ball(sid: str, body: BallIn):
    return _get(sid).add_ball(body)


@app.post("/api/live/{sid}/innings")
def live_innings(sid: str):
    return _get(sid).next_innings()


@app.get("/api/live/{sid}")
def live_state(sid: str):
    s = _get(sid)
    return {"id": sid, "teams": s.teams, "inn": s.inn, "finished": s.finished, "points": s.pts,
            "swings": engine.top_swings(s.pts, s.teams)}


@app.get("/api/live/{sid}/stream")
async def live_stream(sid: str):
    s = _get(sid)
    q = asyncio.Queue()
    s.subs.add(q)

    async def gen():
        try:
            yield sse("hello", {"id": sid, "teams": s.teams, "points": len(s.pts)})
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield sse("point", ev)
                    if ev.get("finished"):
                        yield sse("end", {})
                        return
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            s.subs.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="site")
