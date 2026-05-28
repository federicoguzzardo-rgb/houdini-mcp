"""Translator — maps merged critic feedback to a Houdini action list.

Two modes (project brief §5.2):
  - parametric: tweak parms on existing nodes
  - structural: rebuild a subgraph (triggered by Convergence Judge `stuck`)

Two backends:
  - auto:  Anthropic SDK with tool use (get_parm + submit_actions)
  - human: terminal input() prompt
"""
from __future__ import annotations

import json as _json

from agents.emit import emit, Timer

_TOOLS = [
    {
        "name": "get_parm",
        "description": "Get the current value of a parameter on a Houdini node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_path": {"type": "string", "description": "Full node path e.g. /obj/geo1/box1"},
                "parm_name": {"type": "string", "description": "Parameter name e.g. sizex"},
            },
            "required": ["node_path", "parm_name"],
        },
    },
    {
        "name": "submit_actions",
        "description": "Submit the final list of parameter changes to apply to Houdini.",
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "node":      {"type": "string"},
                            "parm":      {"type": "string"},
                            "value":     {"type": "number"},
                            "change":    {"type": "string"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["node", "parm", "value"],
                    },
                }
            },
            "required": ["actions"],
        },
    },
]


class Translator:
    def __init__(self, mode: str = "parametric", human_mode: bool = False,
                 client=None):
        self.mode = mode
        self.human_mode = human_mode
        self.client = client  # HoudiniClient — used by SDK tool calls

    def translate(self, run_id: str, iteration: int, step_id: str,
                  behavioral: dict, perceptual: dict,
                  graph_json: dict | None = None,
                  prompt: str = "",
                  target_node: str = "") -> dict:
        """Returns the Translator payload (also emitted)."""
        with Timer() as t:

            # ---- human mode ------------------------------------------------
            if self.human_mode:
                first_issue = (perceptual.get("issues") or [{}])[0].get(
                    "description", "none")
                b_status = "PASSED" if behavioral.get("passed") else "FAILED"
                print(f"\n=== Translator — iteration {iteration} | mode: {self.mode} ===")
                print(f"Goal: {prompt}")
                print(f"Behavioral: {b_status}")
                print(f'VLM: intent={perceptual.get("intent_match", "?")} | {first_issue}')
                print(f"Node: {target_node}")
                print("Enter actions — key=value pairs, JSON array, or empty/skip:")
                print("  e.g.  radx=1.5 rady=0.3")
                print('        [{"node":"/obj/geo1/torus1","parm":"radx","value":1.5,...}]')
                raw = input("> ").strip().lstrip("﻿ï»¿")

                if not raw or raw.lower() == "skip":
                    actions, sources = [], ["user_skip"]
                elif raw.startswith("["):
                    actions = _json.loads(raw)
                    sources = ["user"]
                else:
                    actions, sources = [], ["user"]
                    for pair in raw.split():
                        key, _, val = pair.partition("=")
                        if key and val:
                            try:
                                actions.append({
                                    "node": target_node, "parm": key,
                                    "value": float(val), "change": "user",
                                    "rationale": "user input",
                                })
                            except ValueError:
                                pass

                payload = {"source": ["user"], "mode": self.mode,
                           "actions": actions, "fallback": False}

            # ---- auto mode (Anthropic SDK + tool use) ----------------------
            else:
                actions, sources, used_fallback = self._sdk_translate(
                    behavioral, perceptual, graph_json, prompt, target_node
                )
                payload = {"source": sources, "mode": self.mode,
                           "actions": actions, "fallback": used_fallback}

        emit(run_id, iteration, step_id, "translator", "result",
             payload, duration_ms=t.ms)
        return payload

    def _sdk_translate(self, behavioral, perceptual, graph_json, prompt, target_node):
        try:
            import anthropic as _anth
        except ImportError:
            return [], ["fallback"], True

        sys_prompt = (
            "You are a Houdini SOP editor agent. Use get_parm to inspect current "
            f"parameter values, then call submit_actions with all changes needed. "
            f"Translator mode: {self.mode} (parametric = tweak parms; "
            "structural = rebuild subgraph). Only use parm names that exist on "
            "the node type."
        )
        user_msg = (
            f"User goal: {prompt}\n"
            f"Target node: {target_node}\n"
            f"Behavioral result: {_json.dumps(behavioral)}\n"
            f"Perceptual result: {_json.dumps(perceptual)}\n"
            f"Graph: {_json.dumps(graph_json)}\n\n"
            "Inspect the scene with get_parm, then call submit_actions with "
            "the corrective parameter changes. Submit an empty list if no "
            "changes are needed."
        )

        messages = [{"role": "user", "content": user_msg}]
        client = _anth.Anthropic()

        for _ in range(8):  # max tool-use rounds
            try:
                response = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=sys_prompt,
                    tools=_TOOLS,
                    messages=messages,
                )
            except Exception:
                return [], ["fallback"], True

            if response.stop_reason == "end_turn":
                return [], ["llm"], False

            tool_results = []
            submitted_actions = None

            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "get_parm":
                    val = self._get_parm(block.input.get("node_path", ""),
                                         block.input.get("parm_name", ""))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(val),
                    })
                elif block.name == "submit_actions":
                    submitted_actions = block.input.get("actions", [])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "ok",
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            if submitted_actions is not None:
                return submitted_actions, ["llm"], False

        return [], ["fallback"], True

    def _get_parm(self, node_path: str, parm_name: str):
        if self.client is None:
            return 1.0
        try:
            return self.client.get_parm(node_path, parm_name)
        except Exception as e:
            return f"error: {e}"

    def set_mode(self, mode: str):
        self.mode = mode
