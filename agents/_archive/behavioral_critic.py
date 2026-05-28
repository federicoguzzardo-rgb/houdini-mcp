"""Behavioral Critic — facade with three backends.

Modes:
  mock  — iteration-count-based pass/fail. No Houdini needed. Fast dev loop.
  live  — ships agents/behavioral_checks.py source over the wire via
          fxhoudinimcp's `code.execute_python` so the checks run in the
          same Houdini the editor is mutating. No subprocess, no save/load.
  hython — reserved for future per-iteration subprocess use; raises
          NotImplementedError. (The post-loop --validate-with-hython flag
          on the orchestrator already spawns the runner directly.)

Per project brief §7 / §14, payload shape:
  {"passed", "node_path", "structural": [...],
   "parametric": [...], "frame_sweep": [...]}
"""
from __future__ import annotations

from pathlib import Path

from agents.emit import emit, Timer
from agents.houdini_client import (
    FxHoudiniMCPClient, HoudiniBridgeError, HoudiniClient,
)

# Source of the check module, read once and shipped to Houdini per-call.
# behavioral_checks.py deliberately omits `from __future__` so this is safe
# to concatenate after a runtime bootstrap (see _live() below).
_CHECKS_SOURCE = (Path(__file__).resolve().parent /
                  "behavioral_checks.py").read_text(encoding="utf-8")


class BehavioralCritic:
    """Facade. Pick a backend by passing mode="mock" or "live" (or "hython")."""

    def __init__(self, mode: str = "mock", *,
                 client: HoudiniClient | None = None,
                 fail_until_iteration: int = 2,
                 parm_sweep: list[str] | None = None,
                 samples: int = 5):
        self.mode = mode
        self.client = client
        self.fail_until = fail_until_iteration
        self.parm_sweep = parm_sweep or ["sizex", "sizey", "sizez"]
        self.samples = samples

    def evaluate(self, run_id: str, iteration: int, step_id: str,
                 node_path: str = "/obj/geo1/box1") -> dict:
        with Timer() as t:
            if self.mode == "mock":
                payload = self._mock(iteration, node_path)
            elif self.mode == "live":
                payload = self._live(node_path)
            elif self.mode == "hython":
                raise NotImplementedError(
                    "Per-iteration hython mode is intentionally unimplemented "
                    "— use the orchestrator's --validate-with-hython flag for "
                    "a post-loop receipt instead."
                )
            else:
                raise ValueError(f"unknown behavioral mode: {self.mode!r}")
        emit(run_id, iteration, step_id, "behavioral_critic", "result",
             payload, duration_ms=t.ms)
        return payload

    # ---- backends -------------------------------------------------------

    def _mock(self, iteration: int, node_path: str) -> dict:
        passed = iteration > self.fail_until
        return {
            "mode": "mock",
            "passed": passed,
            "node_path": node_path,
            "structural": [
                {"check": "manifold", "passed": True},
                {"check": "nonzero_geo", "passed": True},
                {"check": "nan_positions", "passed": True},
            ],
            "parametric": (
                [] if passed else [
                    {"parm": "sizey", "value": 4.2,
                     "passed": False, "error": "empty output"}
                ]
            ),
            "frame_sweep": [],
        }

    def _live(self, node_path: str) -> dict:
        if not isinstance(self.client, FxHoudiniMCPClient):
            raise RuntimeError(
                "live behavioral mode requires an FxHoudiniMCPClient "
                f"(got {type(self.client).__name__})"
            )

        # Ship the checks module source + a thin bootstrap. The handler's
        # exec() namespace already has hou; behavioral_checks imports it
        # at call sites.
        bootstrap = (
            "import hou\n"
            f"NODE_PATH = {node_path!r}\n"
            f"PARM_SWEEP = {self.parm_sweep!r}\n"
            f"SAMPLES = {self.samples}\n"
        )
        code = bootstrap + _CHECKS_SOURCE
        try:
            payload = self.client.execute_python(
                code,
                return_expression="evaluate(NODE_PATH, PARM_SWEEP, SAMPLES)",
                timeout=120.0,
            )
        except HoudiniBridgeError as e:
            return {
                "mode": "live",
                "passed": False,
                "node_path": node_path,
                "structural": [], "parametric": [], "frame_sweep": [],
                "error": str(e),
            }
        if not isinstance(payload, dict):
            return {
                "mode": "live",
                "passed": False,
                "node_path": node_path,
                "structural": [], "parametric": [], "frame_sweep": [],
                "error": f"unexpected payload type: {type(payload).__name__}",
            }
        payload["mode"] = "live"
        return payload
