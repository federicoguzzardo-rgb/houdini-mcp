"""VLM Critic — perceptual judge. Gated on behavioral pass.

Two modes:
  auto:  claude -p --image subprocess (falls back to neutral score on failure)
  human: pauses, prints context, reads score + issues from terminal
"""
from __future__ import annotations

import json as _json
import subprocess
from pathlib import Path

from agents.emit import emit, Timer


class VLMCritic:
    def __init__(self, client=None, human_mode: bool = False):
        self.client = client
        self.human_mode = human_mode

    def evaluate(self, run_id: str, iteration: int, step_id: str,
                 behavioral_passed: bool,
                 prompt: str = "", node_path: str = "") -> dict:
        if not behavioral_passed:
            payload = {"skipped": True, "reason": "behavioral_fail"}
            emit(run_id, iteration, step_id, "vlm_critic", "skipped",
                 payload, duration_ms=0)
            return payload

        event_type = "result"
        with Timer() as t:
            image_path: str | None = None

            # Capture viewport PNG when running live (both modes)
            try:
                from agents.houdini_client import FxHoudiniMCPClient
                if isinstance(self.client, FxHoudiniMCPClient):
                    render_dir = Path("runs") / run_id / "renders"
                    render_dir.mkdir(parents=True, exist_ok=True)
                    img = str(render_dir / f"{step_id}_viewport.png").replace("\\", "/")
                    self.client.capture_viewport_png(img)
                    image_path = img
            except Exception:
                image_path = None

            # ---- human mode ------------------------------------------------
            if self.human_mode:
                print(f"\n=== VLM — iteration {iteration} — goal: {prompt!r} ===")
                print(f"Behavioral: PASSED | Node: {node_path}")
                if image_path:
                    print(f"Viewport saved: {image_path}")
                print("[Check Houdini viewport now]")
                print('Enter score 0-1 and optional issue (e.g. "0.7 torus too flat")'
                      ' or "done" or "skip":')
                raw = input("> ").strip().lstrip("﻿ï»¿")

                if raw.lower() == "skip":
                    payload = {"skipped": True, "reason": "user_skip"}
                    event_type = "skipped"
                elif not raw or raw.lower() == "done":
                    payload = {"intent_match": 1.0, "issues": [],
                               "observation_ref": image_path}
                else:
                    parts = raw.split(None, 1)
                    try:
                        score = float(parts[0])
                    except ValueError:
                        score = 0.5
                    issues = (
                        [{"type": "user", "description": parts[1], "priority": "medium"}]
                        if len(parts) > 1 else []
                    )
                    payload = {"intent_match": score, "issues": issues,
                               "observation_ref": image_path}

            # ---- auto mode (claude -p) -------------------------------------
            else:
                cli_prompt = (
                    "You are a visual quality judge for Houdini geometry. "
                    "Evaluate how well the geometry matches the user's intent. "
                    "Return ONLY a JSON object: "
                    '{\"intent_match\": <float 0-1>, \"issues\": [{\"type\": \"<str>\", '
                    '\"description\": \"<str>\", \"priority\": \"high|medium|low\"}]}\n\n'
                    f"User goal: {prompt}\n"
                    f"Node: {node_path}\n"
                    f"Iteration: {iteration}\n"
                    + ("Assess the viewport image attached." if image_path
                       else "No image available — assess based on context only.")
                )
                payload = {"intent_match": 0.5, "issues": [], "fallback": True,
                           "observation_ref": image_path}
                try:
                    cmd = ["claude", "-p", cli_prompt, "--output-format", "json"]
                    if image_path and Path(image_path).exists():
                        cmd += ["--image", image_path]
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=90, check=False)
                    if r.returncode == 0:
                        raw_out = _json.loads(r.stdout).get("result", "{}")
                        parsed = _json.loads(raw_out)
                        if isinstance(parsed, dict) and "intent_match" in parsed:
                            payload = {
                                "intent_match": float(parsed["intent_match"]),
                                "issues": parsed.get("issues", []),
                                "observation_ref": image_path,
                            }
                except Exception:
                    pass

        emit(run_id, iteration, step_id, "vlm_critic", event_type,
             payload, duration_ms=t.ms)
        return payload
