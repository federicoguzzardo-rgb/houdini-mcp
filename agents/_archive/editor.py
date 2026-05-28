"""Editor — pure executor. Takes an action list, calls the Houdini client.

Per project brief §5.3 and loop-monitor §0: every action MUST carry an
explicit `node_path` string in the emitted payload.
"""
from __future__ import annotations

from typing import Any

from agents.emit import emit, Timer
from agents.houdini_client import HoudiniClient, HoudiniBridgeError


class Editor:
    def __init__(self, client: HoudiniClient):
        self.client = client

    def execute(self, run_id: str, iteration: int, step_id: str,
                actions: list[dict]) -> dict:
        results: list[dict] = []
        cook_errors: list[dict] = []
        with Timer() as t:
            for a in actions:
                node_path = a.get("node") or a.get("node_path")
                if not node_path:
                    results.append({
                        "node_path": "<missing>",
                        "call": str(a),
                        "result": "error: action missing node/node_path",
                    })
                    continue

                if "parm" in a and "value" in a:
                    r = self.client.set_parm(node_path, a["parm"], a["value"])
                elif a.get("op") == "create":
                    parent = node_path.rsplit("/", 1)[0] or "/obj"
                    name = node_path.rsplit("/", 1)[1]
                    call = f"hou.node('{parent}').createNode('{a['type']}', '{name}')"
                    try:
                        self.client.create_node(parent, a["type"], name)
                        result = "ok"
                    except HoudiniBridgeError as e:
                        msg = str(e).lower()
                        result = ("ok (already exists)"
                                  if "already" in msg or "exists" in msg
                                  else f"error: {e}")
                    r = type("Tmp", (), dict(
                        node_path=node_path, call=call,
                        result=result, before=None, after=None))()
                elif a.get("op") == "cook":
                    r = self.client.cook(node_path)
                else:
                    r = type("Tmp", (), dict(
                        node_path=node_path,
                        call=f"<unsupported action {a}>",
                        result="error: unknown action shape",
                        before=None, after=None))()

                results.append({
                    "node_path": r.node_path,
                    "call": r.call,
                    "result": r.result,
                    "before": r.before,
                    "after": r.after,
                })
                if isinstance(r.result, str) and r.result.startswith("error"):
                    cook_errors.append({"node_path": r.node_path, "error": r.result})

        payload = {
            "actions": results,
            "cook_errors": cook_errors,
            "graph_ref": f"runs/{run_id}/snapshots/{step_id}.json",
        }
        emit(run_id, iteration, step_id, "editor", "result",
             payload, duration_ms=t.ms)
        return payload
