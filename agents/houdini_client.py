"""Thin Houdini bridge — switches between fxhoudinimcp (HTTP) and hrpyc (RPyC).

Phase 4 ships `MockHoudiniClient` and `FxHoudiniMCPClient` (HTTP 127.0.0.1:8100).
HRPyC support is stubbed — wire it in when direct hou-proxy access is needed.

Always pass `node_path` strings — never rpyc proxy objects (INSTRUCTIONS.md §8).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ActionResult:
    node_path: str
    call: str
    result: str  # "ok" or error string
    before: Any = None
    after: Any = None


class HoudiniClient(Protocol):
    """Minimum surface every backend must expose."""
    def create_node(self, parent_path: str, type_name: str, name: str) -> str: ...
    def set_parm(self, node_path: str, parm: str, value: float) -> ActionResult: ...
    def get_parm(self, node_path: str, parm: str) -> float: ...
    def connect(self, src_path: str, dst_path: str, input_index: int = 0) -> ActionResult: ...
    def cook(self, node_path: str) -> ActionResult: ...
    def node_graph_json(self, root: str = "/obj") -> dict: ...


@dataclass
class MockHoudiniClient:
    """In-process mock. Pretends nodes exist; tracks parm state in a dict."""
    parms: dict[tuple[str, str], float] = field(default_factory=dict)
    graph: dict[str, dict] = field(default_factory=lambda: {
        "/obj/geo1": {"type": "geo", "inputs": []},
        "/obj/geo1/box1": {"type": "box", "inputs": []},
    })

    def create_node(self, parent_path, type_name, name):
        path = f"{parent_path}/{name}"
        self.graph[path] = {"type": type_name, "inputs": []}
        return path

    def set_parm(self, node_path, parm, value):
        key = (node_path, parm)
        before = self.parms.get(key, 1.0)
        self.parms[key] = value
        return ActionResult(
            node_path=node_path,
            call=f"hou.node('{node_path}').parm('{parm}').set({value})",
            result="ok",
            before=before,
            after=value,
        )

    def get_parm(self, node_path, parm):
        return self.parms.get((node_path, parm), 1.0)

    def connect(self, src_path, dst_path, input_index=0):
        self.graph.setdefault(dst_path, {"type": "?", "inputs": []})["inputs"].insert(
            input_index, src_path
        )
        return ActionResult(
            node_path=dst_path,
            call=f"hou.node('{dst_path}').setInput({input_index}, hou.node('{src_path}'))",
            result="ok",
        )

    def cook(self, node_path):
        return ActionResult(
            node_path=node_path,
            call=f"hou.node('{node_path}').cook(force=True)",
            result="ok",
        )

    def node_graph_json(self, root="/obj"):
        return {p: meta for p, meta in self.graph.items() if p.startswith(root)}


class HoudiniBridgeError(RuntimeError):
    """Raised when the live fxhoudinimcp HTTP call fails."""


@dataclass
class FxHoudiniMCPClient:
    """Live HTTP client for fxhoudinimcp's hwebserver on 127.0.0.1:8100.

    Wire protocol (per fxhoudinimcp/mcp/.../bridge.py and hwebserver_app.py):

        POST /api
        Content-Type: application/x-www-form-urlencoded
        Body: json=["mcp.execute", [], {"command": "...", "params": {...},
                                         "request_id": "..."}]

    Response: {"status": "success", "data": {...}, "timing_ms": ...}
              or {"status": "error", "error": {...}}
    """
    host: str = "127.0.0.1"
    port: int = 8100
    timeout: float = 60.0

    @property
    def _url(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    def _rpc(self, command: str, params: dict | None = None,
             timeout: float | None = None) -> dict:
        body = urllib.parse.urlencode({
            "json": json.dumps([
                "mcp.execute", [],
                {"command": command, "params": params or {},
                 "request_id": uuid.uuid4().hex},
            ])
        }).encode("utf-8")
        req = urllib.request.Request(self._url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                result = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise HoudiniBridgeError(
                f"Cannot reach fxhoudinimcp at {self._url}. "
                "Is Houdini open with the plugin loaded?"
            ) from e

        if isinstance(result, dict) and result.get("status") == "error":
            raise HoudiniBridgeError(
                f"{command}: {result.get('error', {}).get('message', 'unknown')}"
            )
        if isinstance(result, dict) and result.get("status") == "success":
            return result.get("data", {})
        return result

    # ---- HoudiniClient protocol -----------------------------------------

    def create_node(self, parent_path: str, type_name: str, name: str) -> str:
        out = self._rpc("nodes.create_node", {
            "parent_path": parent_path,
            "node_type": type_name,
            "name": name,
        })
        return out.get("node_path", f"{parent_path}/{name}")

    def set_parm(self, node_path: str, parm: str, value: float) -> ActionResult:
        try:
            before = self.get_parm(node_path, parm)
        except HoudiniBridgeError:
            before = None
        try:
            out = self._rpc("parameters.set_parameter", {
                "node_path": node_path,
                "parm_name": parm,
                "value": value,
            })
            return ActionResult(
                node_path=node_path,
                call=f"hou.node('{node_path}').parm('{parm}').set({value})",
                result="ok",
                before=before,
                after=out.get("new_value", value),
            )
        except HoudiniBridgeError as e:
            return ActionResult(
                node_path=node_path,
                call=f"hou.node('{node_path}').parm('{parm}').set({value})",
                result=f"error: {e}",
                before=before,
                after=None,
            )

    def get_parm(self, node_path: str, parm: str) -> float:
        out = self._rpc("parameters.get_parameter", {
            "node_path": node_path,
            "parm_name": parm,
        })
        # parameters.get_parameter returns {"value": ..., "raw_value": ...}
        return out.get("value")

    def connect(self, src_path: str, dst_path: str, input_index: int = 0):
        try:
            self._rpc("nodes.connect_nodes", {
                "source_path": src_path,
                "dest_path": dst_path,
                "input_index": input_index,
            })
            return ActionResult(
                node_path=dst_path,
                call=f"hou.node('{dst_path}').setInput({input_index}, hou.node('{src_path}'))",
                result="ok",
            )
        except HoudiniBridgeError as e:
            return ActionResult(
                node_path=dst_path,
                call=f"connect({src_path} -> {dst_path}[{input_index}])",
                result=f"error: {e}",
            )

    def execute_python(self, code: str, return_expression: str | None = None,
                       timeout: float | None = None):
        """Run arbitrary Python inside Houdini. Returns return_value directly.

        Wraps fxhoudinimcp's `code.execute_python` handler — its response
        envelope is `{"executed": True, "return_value": ...}` on success,
        `{"executed": False, "error": "..."}` on exec failure.
        """
        out = self._rpc("code.execute_python", {
            "code": code,
            "return_expression": return_expression,
        }, timeout=timeout)
        if not isinstance(out, dict):
            return out
        if out.get("executed") is False:
            raise HoudiniBridgeError(
                f"execute_python: {out.get('error', 'unknown')}"
            )
        if "eval_error" in out:
            raise HoudiniBridgeError(
                f"execute_python eval: {out.get('eval_error')}"
            )
        return out.get("return_value")

    def cook(self, node_path: str) -> ActionResult:
        code = (
            f"node = hou.node({node_path!r})\n"
            f"hou.node({node_path!r}).cook(force=True)\n"
        )
        try:
            errors = self.execute_python(
                code,
                return_expression=(
                    f"list(hou.node({node_path!r}).errors()) "
                    f"if hou.node({node_path!r}) else ['node not found']"
                ),
            ) or []
            return ActionResult(
                node_path=node_path,
                call=f"hou.node('{node_path}').cook(force=True)",
                result="ok" if not errors else f"error: {errors}",
            )
        except HoudiniBridgeError as e:
            return ActionResult(
                node_path=node_path,
                call=f"hou.node('{node_path}').cook(force=True)",
                result=f"error: {e}",
            )

    def node_graph_json(self, root: str = "/obj") -> dict:
        code = (
            f"root = hou.node({root!r})\n"
            "out = {}\n"
            "if root is not None:\n"
            "    for n in [root] + list(root.allSubChildren()):\n"
            "        out[n.path()] = {\n"
            "            'type': n.type().name(),\n"
            "            'inputs': [i.path() if i else None for i in n.inputs()],\n"
            "        }\n"
        )
        try:
            return self.execute_python(code, return_expression="out") or {}
        except HoudiniBridgeError:
            return {}

    def health(self) -> dict:
        """Fast endpoint to confirm Houdini + plugin are reachable."""
        body = urllib.parse.urlencode({
            "json": json.dumps(["mcp.health", [], {}]),
        }).encode("utf-8")
        req = urllib.request.Request(self._url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise HoudiniBridgeError(f"health check failed: {e}") from e


def make_client(mode: str = "mock") -> HoudiniClient:
    """Factory used by the orchestrator. `mode` is "mock" or "fx" (fxhoudinimcp)."""
    if mode == "mock":
        return MockHoudiniClient()
    if mode == "fx":
        return FxHoudiniMCPClient()
    raise ValueError(f"unknown client mode: {mode!r}")
