"""Shared event-log reader. Imported by both the Streamlit and Houdini UIs."""
import json
from pathlib import Path
from collections import defaultdict


def read_events(path):
    """Parse events.jsonl. Tolerates a partial trailing line (live append)."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def group_by_iteration(events):
    """-> {iteration_number: {'number': n, 'events': [...]}}"""
    grouped = defaultdict(lambda: {"number": None, "events": []})
    for e in events:
        n = e.get("iteration")
        if n is None:
            continue
        grouped[n]["number"] = n
        grouped[n]["events"].append(e)
    return dict(grouped)


def find_event(iteration, agent):
    """Last payload emitted by `agent` within an iteration bucket."""
    hits = [e for e in iteration["events"] if e.get("agent") == agent]
    return hits[-1]["payload"] if hits else {}


def latest_status(events):
    """Most recent convergence-judge decision + iteration count."""
    state, iteration = "running", 0
    for e in events:
        iteration = max(iteration, e.get("iteration", 0))
        if e.get("agent") == "convergence_judge":
            d = e.get("payload", {}).get("decision")
            state = {"done": "converged",
                     "stuck": "stuck",
                     "continue": "running"}.get(d, state)
    return {"state": state, "iteration": iteration}


def build_convergence_series(iters):
    """Rows for the intent_match / behavioral_pass_rate chart."""
    rows = []
    for n in sorted(iters):
        cj = find_event(iters[n], "convergence_judge")
        rows.append({
            "iteration": n,
            "intent_match": cj.get("intent_match"),
            "behavioral_pass_rate": cj.get("behavioral_pass_rate"),
        })
    return rows
