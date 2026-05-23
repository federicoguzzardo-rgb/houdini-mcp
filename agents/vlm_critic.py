"""VLM Critic — perceptual judge. Gated on behavioral pass.

Phase 3 ships a mock that returns intent_match climbing across iterations.
Phase 5 wires a real VLM (GPT-4V / Claude vision) using the 4-view
observation package per project brief §6.
"""
from __future__ import annotations

from agents.emit import emit, Timer


class VLMCritic:
    def __init__(self):
        # mock curve: intent_match per iteration
        self._curve = {3: 0.55, 4: 0.72, 5: 0.84, 6: 0.88, 7: 0.91}

    def evaluate(self, run_id: str, iteration: int, step_id: str,
                 behavioral_passed: bool) -> dict:
        if not behavioral_passed:
            # Gated out — emit a marker event so the timeline reflects "skipped"
            payload = {"skipped": True, "reason": "behavioral_fail"}
            emit(run_id, iteration, step_id, "vlm_critic", "skipped",
                 payload, duration_ms=0)
            return payload

        with Timer() as t:
            intent = self._curve.get(iteration, 0.92)
            issues = (
                [{"type": "proportion",
                  "description": "bevels too uniform",
                  "priority": "high"}]
                if intent < 0.8 else
                [{"type": "minor",
                  "description": "looks close to target",
                  "priority": "low"}]
            )
            payload = {
                "intent_match": intent,
                "issues": issues,
                "observation_ref": f"runs/{run_id}/renders/{step_id}_composed.png",
            }
        emit(run_id, iteration, step_id, "vlm_critic", "result",
             payload, duration_ms=t.ms)
        return payload
