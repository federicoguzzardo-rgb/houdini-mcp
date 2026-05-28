"""Convergence Judge — text-only, lightweight. Decides continue / done / stuck.

Per project brief §5.4 and §8:
  DONE  = behavioral.passed AND intent_match >= 0.8 AND delta < 0.05
  STUCK = no improvement in last 3 iterations
  CONT  = otherwise
"""
from __future__ import annotations

from agents.emit import emit, Timer


class ConvergenceJudge:
    def __init__(self, intent_threshold: float = 0.8,
                 delta_epsilon: float = 0.05,
                 stuck_window: int = 3):
        self.threshold = intent_threshold
        self.epsilon = delta_epsilon
        self.window = stuck_window
        self._history: list[dict] = []

    def decide(self, run_id: str, iteration: int, step_id: str,
               behavioral: dict, vlm: dict) -> dict:
        with Timer() as t:
            behavioral_passed = bool(behavioral.get("passed"))
            intent = vlm.get("intent_match")
            self._history.append({
                "iteration": iteration,
                "behavioral_passed": behavioral_passed,
                "intent_match": intent,
            })

            delta = self._delta(intent)
            decision = self._decide(behavioral_passed, intent, delta)
            payload = {
                "decision": decision,
                "intent_match": intent if intent is not None else 0.0,
                "behavioral_pass_rate": self._behavioral_rate(),
                "delta": delta if delta is not None else 0.0,
                "reason": self._reason(decision, behavioral_passed, intent, delta),
            }
        emit(run_id, iteration, step_id, "convergence_judge", "result",
             payload, duration_ms=t.ms)
        return payload

    def _delta(self, intent):
        prevs = [h["intent_match"] for h in self._history[:-1]
                 if h["intent_match"] is not None]
        if intent is None or not prevs:
            return None
        return abs(intent - prevs[-1])

    def _behavioral_rate(self):
        if not self._history:
            return 0.0
        passed = sum(1 for h in self._history if h["behavioral_passed"])
        return passed / len(self._history)

    def _decide(self, behavioral_passed, intent, delta):
        if (behavioral_passed and intent is not None
                and intent >= self.threshold
                and delta is not None and delta < self.epsilon):
            return "done"

        if len(self._history) >= self.window:
            tail = [h["intent_match"] for h in self._history[-self.window:]
                    if h["intent_match"] is not None]
            if len(tail) == self.window and max(tail) - min(tail) < self.epsilon:
                # plateaued for `window` iterations without converging
                if intent is None or intent < self.threshold:
                    return "stuck"
        return "continue"

    @staticmethod
    def _reason(decision, behavioral_passed, intent, delta):
        if decision == "done":
            return "converged"
        if decision == "stuck":
            return f"no improvement in last window; intent_match={intent}"
        if not behavioral_passed:
            return "behavioral fail — fix structure first"
        return f"improving, intent_match={intent} delta={delta}"
