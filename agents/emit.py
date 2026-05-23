"""Single helper used by every agent. Appends one JSON line to
runs/<run_id>/events.jsonl per project brief §14 envelope."""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def new_run_id():
    return uuid.uuid4().hex[:12]


def run_dir(run_id):
    p = RUNS_DIR / run_id
    (p / "snapshots").mkdir(parents=True, exist_ok=True)
    (p / "renders").mkdir(parents=True, exist_ok=True)
    return p


def events_path(run_id):
    return run_dir(run_id) / "events.jsonl"


def emit(run_id, iteration, step_id, agent, event_type, payload, duration_ms=0):
    """Append one JSON-line event. Returns the event dict."""
    event = {
        "run_id": run_id,
        "iteration": iteration,
        "step_id": step_id,
        "agent": agent,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "duration_ms": duration_ms,
        "payload": payload,
    }
    path = events_path(run_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event


class Timer:
    """Tiny helper for duration_ms in emit() — `with Timer() as t: ...; t.ms`."""
    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc):
        self.ms = int((time.perf_counter() - self._t0) * 1000)
