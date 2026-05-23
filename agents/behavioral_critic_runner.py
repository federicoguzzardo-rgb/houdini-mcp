"""Behavioral Critic — hython entrypoint (runs headless, no GUI).

Spawned by the orchestrator as:

    hython agents/behavioral_critic_runner.py \\
        --hip-file scenes/current.hip \\
        --node-path /obj/geo1/box1 \\
        --run-id <uuid> \\
        --iteration <n> \\
        --step-id <n>.1 \\
        --event-type result \\
        --parm-sweep sizex sizey sizez

Check logic lives in agents/behavioral_checks.py and is shared with the
in-loop live backend.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.behavioral_checks import evaluate  # noqa: E402
from agents.emit import emit  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hip-file", default=None,
                   help="Optional .hip to load before evaluating")
    p.add_argument("--node-path", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--iteration", type=int, required=True)
    p.add_argument("--step-id", required=True)
    p.add_argument("--event-type", default="result",
                   help="Set to 'post_validation' when called as a "
                        "post-loop receipt; 'result' otherwise.")
    p.add_argument("--parm-sweep", nargs="*", default=[],
                   help="Parameter names to sweep")
    args = p.parse_args()

    t0 = time.perf_counter()
    try:
        import hou  # noqa: F401
        if args.hip_file:
            hou.hipFile.load(args.hip_file, ignore_load_warnings=True)
        payload = evaluate(args.node_path, args.parm_sweep)
    except Exception as e:
        payload = {
            "passed": False, "node_path": args.node_path,
            "structural": [], "parametric": [], "frame_sweep": [],
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    duration_ms = int((time.perf_counter() - t0) * 1000)
    emit(args.run_id, args.iteration, args.step_id, "behavioral_critic",
         args.event_type, payload, duration_ms=duration_ms)
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
