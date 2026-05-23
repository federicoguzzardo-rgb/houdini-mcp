"""Emit a synthetic 5-iteration events.jsonl to validate the dashboard
before any Houdini is wired in.

Run:  python scripts/mock_run.py [--run-id mock-01]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.emit import emit, run_dir, events_path


def _scenario(iteration):
    """Return per-agent payloads for a single iteration.

    Iteration 1: behavioral fails (empty output at extreme parm).
    Iteration 2: behavioral fails (different parm).
    Iteration 3: behavioral passes, VLM low intent_match.
    Iteration 4: behavioral passes, VLM intent climbing.
    Iteration 5: behavioral passes, intent_match >= 0.8, delta < 0.05 -> done.
    """
    base = {
        "translator_node": "/obj/geo1/box1",
        "parm": "sizey",
        "before": 1.0 + 0.1 * (iteration - 1),
    }
    behavioral_pass = iteration >= 3
    intent = [None, None, 0.55, 0.72, 0.84][iteration - 1] if iteration <= 5 else 0.84
    delta = [None, None, None, 0.17, 0.04][iteration - 1] if iteration <= 5 else 0.0
    decision = "done" if iteration == 5 else "continue"

    behavioral = {
        "passed": behavioral_pass,
        "structural": [
            {"check": "manifold", "passed": True},
            {"check": "nonzero_geo", "passed": True},
        ],
        "parametric": (
            [] if behavioral_pass else [
                {"parm": base["parm"], "value": 4.2,
                 "passed": False, "error": "empty output"}
            ]
        ),
    }
    vlm = (
        {} if not behavioral_pass else {
            "intent_match": intent,
            "issues": [
                {"type": "proportion",
                 "description": "bevels too uniform" if iteration < 5 else "looks good",
                 "priority": "high" if iteration < 5 else "low"}
            ],
            "observation_ref": f"runs/mock-01/renders/{iteration}_composed.png",
        }
    )
    translator = {
        "source": ["behavioral"] if not behavioral_pass else ["perceptual"],
        "mode": "parametric" if iteration < 5 else "parametric",
        "actions": [
            {"node": base["translator_node"],
             "parm": base["parm"],
             "change": "increase ~30%" if iteration % 2 else "decrease ~10%",
             "rationale": "fix proportion" if behavioral_pass else "avoid empty output"}
        ],
    }
    editor = {
        "actions": [
            {"node_path": base["translator_node"],
             "call": f"box1.parm('{base['parm']}').set({base['before'] + 0.3:.2f})",
             "result": "ok",
             "before": base["before"],
             "after": base["before"] + 0.3},
        ],
        "cook_errors": [],
        "graph_ref": f"runs/mock-01/snapshots/{iteration}_2.json",
    }
    judge = {
        "decision": decision,
        "intent_match": intent if intent is not None else 0.0,
        "behavioral_pass_rate": 1.0 if behavioral_pass else 0.0,
        "delta": delta if delta is not None else 0.0,
        "reason": (
            "behavioral fail — fix structure" if not behavioral_pass
            else "converged" if decision == "done"
            else "improving, below threshold"
        ),
    }
    return behavioral, vlm, translator, editor, judge


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="mock-01")
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--delay", type=float, default=0.0,
                   help="seconds between iterations (for live-stream demos)")
    args = p.parse_args()

    rd = run_dir(args.run_id)
    # fresh start: truncate events
    ep = events_path(args.run_id)
    if ep.exists():
        ep.unlink()

    emit(args.run_id, 0, "0.0", "orchestrator", "start",
         {"prompt": "create a brick wall"})

    for it in range(1, args.iterations + 1):
        behavioral, vlm, translator, editor, judge = _scenario(it)

        emit(args.run_id, it, f"{it}.1", "behavioral_critic", "result",
             behavioral, duration_ms=340)
        if vlm:
            emit(args.run_id, it, f"{it}.2", "vlm_critic", "result",
                 vlm, duration_ms=2200)
        emit(args.run_id, it, f"{it}.3", "translator", "result",
             translator, duration_ms=180)
        emit(args.run_id, it, f"{it}.4", "editor", "result",
             editor, duration_ms=95)
        emit(args.run_id, it, f"{it}.5", "convergence_judge", "result",
             judge, duration_ms=20)

        if args.delay:
            time.sleep(args.delay)

    print(f"wrote {ep}")
    print(f"runs dir: {rd}")


if __name__ == "__main__":
    main()
