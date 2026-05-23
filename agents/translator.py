"""Translator — maps merged critic feedback to a Houdini action list.

Mocked logic: deterministic rules per iteration so the loop completes
without an LLM. Phase 4+ wires this to a real model.

Two modes (project brief §5.2):
  - parametric: tweak parms on existing nodes
  - structural: rebuild a subgraph (triggered by Convergence Judge `stuck`)
"""
from __future__ import annotations

from agents.emit import emit, Timer


class Translator:
    def __init__(self, mode: str = "parametric"):
        self.mode = mode

    def translate(self, run_id: str, iteration: int, step_id: str,
                  behavioral: dict, perceptual: dict,
                  graph_json: dict | None = None) -> dict:
        """Returns the Translator payload (also emitted)."""
        sources: list[str] = []
        actions: list[dict] = []

        with Timer() as t:
            # Behavioral failures take priority (mechanical translation).
            param_failures = behavioral.get("parametric", []) if behavioral else []
            if param_failures and not behavioral.get("passed", True):
                sources.append("behavioral")
                for f in param_failures:
                    actions.append({
                        "node": "/obj/geo1/box1",
                        "parm": f.get("parm", "sizey"),
                        "value": 1.0,  # safe default — back away from breakage
                        "change": "reset to safe default",
                        "rationale": f"behavioral fail: {f.get('error', 'unknown')}",
                    })

            # Otherwise translate perceptual feedback.
            if not actions and perceptual:
                sources.append("perceptual")
                intent = perceptual.get("intent_match", 0.0)
                # Toy heuristic: nudge sizey by an amount that shrinks with intent.
                delta = max(0.05, 0.4 * (1.0 - intent))
                actions.append({
                    "node": "/obj/geo1/box1",
                    "parm": "sizey",
                    "value": round(1.0 + iteration * 0.15, 3),
                    "change": f"increase by {delta:.2f}",
                    "rationale": (perceptual.get("issues", [{}])[0].get(
                        "description", "perceptual nudge"
                    )),
                })

        payload = {
            "source": sources,
            "mode": self.mode,
            "actions": actions,
        }
        emit(run_id, iteration, step_id, "translator", "result",
             payload, duration_ms=t.ms)
        return payload

    def set_mode(self, mode: str):
        self.mode = mode
