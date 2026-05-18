from PySide2 import QtWidgets, QtCore, QtGui
import threading
import json
import os
import re

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# ── Houdini UI palette ────────────────────────────────────────────────────────
_BG        = "#3b3b3b"
_BG_DARK   = "#2d2d2d"
_BG_PANEL  = "#404040"
_BG_INPUT  = "#2a2a2a"
_BORDER    = "#222222"
_TEXT      = "#d2d2d2"
_TEXT_DIM  = "#888888"
_ORANGE    = "#e07c00"
_ORANGE_HV = "#f08c10"
_CODE_FG   = "#c8c8a0"
_BTN_BG    = "#525252"
_BTN_HV    = "#626262"

# ── Tool definitions (Anthropic tool_use format) ──────────────────────────────
TOOLS = [
    {
        "name": "scene_summary",
        "description": "Get an overview of the current Houdini scene: all /obj children, current frame, frame range.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_children",
        "description": "List child nodes inside any network path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Network path, e.g. /obj or /obj/geo1"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_node_info",
        "description": "Get type, key parameters, inputs, outputs, errors and warnings for a node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_node_types",
        "description": "Search available node types in a context. Always call this before create_node to verify the type name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Sop, Dop, Object, Vop, Chop, Lop, etc."},
                "filter": {"type": "string", "description": "Keyword to filter results (optional)"},
            },
            "required": ["context"],
        },
    },
    {
        "name": "create_node",
        "description": "Create a node inside a parent network.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_path": {"type": "string"},
                "node_type":   {"type": "string"},
                "name":        {"type": "string", "description": "Optional name override"},
            },
            "required": ["parent_path", "node_type"],
        },
    },
    {
        "name": "delete_node",
        "description": "Delete a node by path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "set_parameter",
        "description": "Set a single parameter on a node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_path":  {"type": "string"},
                "parm_name":  {"type": "string"},
                "value":      {"description": "String, number, or list of numbers for vector parms"},
            },
            "required": ["node_path", "parm_name", "value"],
        },
    },
    {
        "name": "set_parameters",
        "description": "Set multiple parameters at once. More efficient than repeated set_parameter calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_path": {"type": "string"},
                "parms": {
                    "type": "object",
                    "description": "Dict of {parm_name: value}",
                    "additionalProperties": True,
                },
            },
            "required": ["node_path", "parms"],
        },
    },
    {
        "name": "get_parameter",
        "description": "Read a parameter value from a node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_path":  {"type": "string"},
                "parm_name":  {"type": "string"},
            },
            "required": ["node_path", "parm_name"],
        },
    },
    {
        "name": "connect_nodes",
        "description": "Wire the output of one node into the input of another.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_path":    {"type": "string", "description": "Output (upstream) node path"},
                "to_path":      {"type": "string", "description": "Input (downstream) node path"},
                "output_index": {"type": "integer", "default": 0},
                "input_index":  {"type": "integer", "default": 0},
            },
            "required": ["from_path", "to_path"],
        },
    },
    {
        "name": "find_errors",
        "description": "Scan the scene for nodes with errors or warnings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_python",
        "description": (
            "Execute arbitrary Python using the hou module. "
            "Last resort — prefer the dedicated tools above. "
            "Set _result in the code to return a value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "call_houdini",
        "description": (
            "Call any fxhoudinimcp command directly on Houdini's plugin server. "
            "Gives access to 70+ specialized commands not covered by the other tools.\n\n"
            "Available commands (namespace.command):\n"
            "  scene: get_scene_info, save_scene, export_file, import_file, get_context_info\n"
            "  context: get_scene_summary, get_selection, set_selection, get_node_errors_detailed\n"
            "  nodes: create_node, delete_node, copy_node, find_nodes, get_node_info, "
            "list_children, list_node_types, layout_children, disconnect_node, set_node_flags\n"
            "  parameters: get_parameter_schema, create_spare_parameter, create_spare_parameters\n"
            "  geometry: get_points, get_prims, get_prim_intrinsics\n"
            "  animation: get_frame, set_frame, set_keyframe, playbar_control\n"
            "  viewport: capture_screenshot, capture_network_editor, render_viewport, "
            "render_quad_view, frame_all, frame_selection, get_viewport_info, list_panes, "
            "set_viewport_camera, set_viewport_direction, set_viewport_display, set_viewport_renderer\n"
            "  rendering: start_render, create_render_node, list_render_nodes\n"
            "  vex: create_wrangle, validate_vex\n"
            "  hda: get_hda_info, list_installed_hdas, reload_hda, update_hda, uninstall_hda\n"
            "  materials: create_material_network, list_material_types\n"
            "  lops: create_lop_node, create_light, list_usd_prims, get_usd_attribute\n"
            "  tops: get_pdg_graph, pause_top_cook\n"
            "  chops: create_chop_node, get_chop_data\n"
            "  cops: create_cop_node, get_cop_info, list_cop_node_types, set_cop_flags\n"
            "  takes: create_take, get_current_take, list_takes\n"
            "  cache: clear_cache, write_cache\n"
            "  code: execute_python, execute_hscript, get_env_variable\n"
            "  workflow: build_sop_chain, setup_render, create_material"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command name, e.g. 'workflow.build_sop_chain' or 'viewport.capture_screenshot'",
                },
                "params": {
                    "type": "object",
                    "description": "Parameters for the command (see fxhoudinimcp docs for each command's params)",
                    "additionalProperties": True,
                },
            },
            "required": ["command"],
        },
    },
]

SYSTEM_PROMPT = """\
You are a Houdini 19.5 VFX assistant embedded inside Houdini with direct scene access via tools.

TOOL PRIORITY (highest to lowest):
1. call_houdini — use for workflow/setup commands: workflow.build_sop_chain,
   workflow.setup_render, viewport.capture_screenshot, vex.create_wrangle,
   rendering.start_render, hda.*, materials.*, lops.*, animation.*, etc.
2. create_node / connect_nodes / set_parameters — for manual network building.
3. scene_summary / get_node_info / list_node_types / find_errors — for inspection.
4. run_python — absolute last resort.

WORKFLOW — follow this every time:
1. Call scene_summary or call_houdini(context.get_scene_summary) to understand current state.
2. Call list_node_types or call_houdini(nodes.list_node_types) before creating nodes.
3. Build with the highest-priority tool that fits (workflow commands first).
4. After building, call find_errors or call_houdini(context.get_node_errors_detailed).
5. Take a screenshot with call_houdini(viewport.capture_screenshot) to verify geometry results.
6. Reply with a short summary.

Rules:
- Never guess node type or parameter names — verify first.
- Prefer set_parameters (batch) over repeated set_parameter.
- Keep prose short. The tools do the work.\
"""


# ── Tool request bridge (background thread → Qt main thread) ─────────────────

class _ToolRequest:
    def __init__(self, name, inputs):
        self.name   = name
        self.inputs = inputs
        self.result = None
        self._done  = threading.Event()

    def wait(self):
        self._done.wait()
        return self.result

    def complete(self, result):
        self.result = result
        self._done.set()


# ── Code display widget (read-only, no execute button) ───────────────────────

class CodeBlock(QtWidgets.QFrame):
    def __init__(self, code, lang, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background: {_BG_DARK}; border: 1px solid {_BORDER}; border-radius: 2px; }}")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if lang:
            bar = QtWidgets.QWidget()
            bar.setStyleSheet(f"background: {_BORDER};")
            bar.setFixedHeight(18)
            bl = QtWidgets.QHBoxLayout(bar)
            bl.setContentsMargins(6, 0, 6, 0)
            ll = QtWidgets.QLabel(lang)
            ll.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
            bl.addWidget(ll)
            layout.addWidget(bar)
        editor = QtWidgets.QPlainTextEdit()
        editor.setPlainText(code)
        editor.setReadOnly(True)
        editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: transparent; color: {_CODE_FG};
                font-family: Consolas, monospace; font-size: 11px;
                border: none; padding: 6px;
            }}
        """)
        line_count = code.count("\n") + 1
        editor.setFixedHeight(min(300, max(36, line_count * 17 + 12)))
        layout.addWidget(editor)


# ── Message bubble ────────────────────────────────────────────────────────────

class MessageBubble(QtWidgets.QFrame):
    def __init__(self, role, content, parent=None):
        super().__init__(parent)
        is_user = role == "user"
        self.setStyleSheet(f"""
            QFrame {{
                background: {_BG_PANEL if is_user else _BG};
                border: 1px solid {_BORDER}; border-radius: 2px;
            }}
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(5)

        chip = QtWidgets.QLabel("  You  " if is_user else "  Claude  ")
        chip.setFixedHeight(18)
        chip.setStyleSheet(f"""
            QLabel {{
                background: {_ORANGE if is_user else _BTN_BG};
                color: {"#1a1a1a" if is_user else _TEXT_DIM};
                font-size: 10px; font-weight: bold; border-radius: 2px;
            }}
        """)
        chip.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(chip)

        for part in _parse_content(content):
            if part["type"] == "text":
                lbl = QtWidgets.QLabel(part["text"])
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                lbl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; background: transparent; border: none;")
                layout.addWidget(lbl)
            else:
                layout.addWidget(CodeBlock(part["code"], part["lang"]))


def _parse_content(content):
    parts = []
    last = 0
    for m in re.finditer(r"```(\w*)\s*\n([\s\S]*?)```", content):
        if m.start() > last:
            t = content[last:m.start()].strip()
            if t:
                parts.append({"type": "text", "text": t})
        parts.append({"type": "code", "lang": m.group(1), "code": m.group(2).rstrip()})
        last = m.end()
    if last < len(content):
        t = content[last:].strip()
        if t:
            parts.append({"type": "text", "text": t})
    return parts


# ── Tool status chip (shown while agent is working) ───────────────────────────

class ToolChip(QtWidgets.QLabel):
    def __init__(self, tool_name, parent=None):
        super().__init__(f"  → {tool_name}  ", parent)
        self.setFixedHeight(18)
        self.setStyleSheet(f"""
            QLabel {{
                background: {_BG_DARK}; color: {_ORANGE};
                font-size: 10px; font-family: Consolas, monospace;
                border: 1px solid {_BORDER}; border-radius: 2px;
            }}
        """)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)


# ── Main panel ────────────────────────────────────────────────────────────────

class ClaudePanel(QtWidgets.QWidget):
    _response_signal     = QtCore.Signal(str)
    _tool_status_signal  = QtCore.Signal(str)        # tool name being called
    _tool_execute_signal = QtCore.Signal(object)     # _ToolRequest → main thread

    def __init__(self, parent=None):
        super().__init__(parent)
        # api_history holds full message list including tool_use / tool_result blocks
        self.api_history  = []
        self.client       = None
        self._response_signal.connect(self._show_response)
        self._tool_status_signal.connect(self._show_tool_status)
        self._tool_execute_signal.connect(self._on_tool_execute)
        self._build_ui()
        self._init_client()

    # ── init ─────────────────────────────────────────────────────────────────

    def _init_client(self):
        if not ANTHROPIC_AVAILABLE:
            return
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            self.client = anthropic.Anthropic(api_key=key)
            self._key_bar.hide()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(f"background: {_BG}; color: {_TEXT};")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QtWidgets.QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet(f"background: {_BG_DARK}; border-bottom: 1px solid {_BORDER};")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 8, 0)
        diamond = QtWidgets.QLabel("◆")
        diamond.setStyleSheet(f"color: {_ORANGE}; font-size: 10px; background: transparent;")
        title = QtWidgets.QLabel("Claude AI")
        title.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {_TEXT}; background: transparent;")
        model_lbl = QtWidgets.QLabel("sonnet-4-6")
        model_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.setFixedHeight(20)
        clear_btn.setStyleSheet(f"""
            QPushButton {{ background: {_BTN_BG}; color: {_TEXT_DIM}; border: none; border-radius: 2px; font-size: 10px; padding: 0 7px; }}
            QPushButton:hover {{ background: {_BTN_HV}; color: {_TEXT}; }}
        """)
        clear_btn.clicked.connect(self._clear_chat)
        hl.addWidget(diamond); hl.addSpacing(5); hl.addWidget(title)
        hl.addSpacing(8); hl.addWidget(model_lbl); hl.addStretch(); hl.addWidget(clear_btn)
        root.addWidget(header)

        # API key bar
        self._key_bar = QtWidgets.QWidget()
        self._key_bar.setStyleSheet(f"background: {_BG_DARK}; border-bottom: 1px solid {_BORDER};")
        kl = QtWidgets.QHBoxLayout(self._key_bar)
        kl.setContentsMargins(8, 3, 8, 3); kl.setSpacing(5)
        key_lbl = QtWidgets.QLabel("API Key:")
        key_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; background: transparent;")
        kl.addWidget(key_lbl)
        self._key_input = QtWidgets.QLineEdit()
        self._key_input.setPlaceholderText("sk-ant-...")
        self._key_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self._key_input.setFixedHeight(22)
        self._key_input.setStyleSheet(f"background: {_BG_INPUT}; color: {_TEXT}; border: 1px solid {_BORDER}; border-radius: 2px; padding: 1px 5px; font-size: 11px;")
        self._key_input.returnPressed.connect(self._set_key)
        kl.addWidget(self._key_input, 1)
        set_btn = QtWidgets.QPushButton("Set")
        set_btn.setFixedSize(36, 22)
        set_btn.setStyleSheet(f"QPushButton {{ background: {_ORANGE}; color: #1a1a1a; border: none; border-radius: 2px; font-size: 11px; font-weight: bold; }} QPushButton:hover {{ background: {_ORANGE_HV}; }}")
        set_btn.clicked.connect(self._set_key)
        kl.addWidget(set_btn)
        root.addWidget(self._key_bar)
        if os.environ.get("ANTHROPIC_API_KEY"):
            self._key_bar.hide()

        if not ANTHROPIC_AVAILABLE:
            warn = QtWidgets.QLabel("  anthropic not installed.\n  Run: hython -m pip install anthropic\n  Then restart Houdini.")
            warn.setStyleSheet(f"color: #e06060; padding: 14px; font-family: Consolas, monospace; font-size: 11px;")
            root.addWidget(warn)

        # Chat scroll
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {_BG}; }}
            QScrollBar:vertical {{ width: 5px; background: {_BG}; }}
            QScrollBar::handle:vertical {{ background: {_BTN_BG}; border-radius: 2px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._chat_inner = QtWidgets.QWidget()
        self._chat_inner.setStyleSheet(f"background: {_BG};")
        self._chat_layout = QtWidgets.QVBoxLayout(self._chat_inner)
        self._chat_layout.setContentsMargins(7, 7, 7, 7)
        self._chat_layout.setSpacing(6)
        self._chat_layout.addStretch()
        self._scroll.setWidget(self._chat_inner)
        root.addWidget(self._scroll, 1)

        # Input bar
        input_bar = QtWidgets.QWidget()
        input_bar.setStyleSheet(f"background: {_BG_DARK}; border-top: 1px solid {_BORDER};")
        input_bar.setFixedHeight(62)
        il = QtWidgets.QHBoxLayout(input_bar)
        il.setContentsMargins(7, 6, 7, 6); il.setSpacing(5)
        self._input = _ChatInput()
        self._input.setPlaceholderText("Ask Claude about your scene…  (Shift+Enter for newline)")
        self._input.send_requested.connect(self.send)
        self._input.setStyleSheet(f"""
            QTextEdit {{ background: {_BG_INPUT}; color: {_TEXT}; border: 1px solid {_BORDER}; border-radius: 2px; padding: 3px 5px; font-size: 12px; }}
            QTextEdit:focus {{ border-color: {_ORANGE}; }}
        """)
        il.addWidget(self._input, 1)
        self._send_btn = QtWidgets.QPushButton("▶")
        self._send_btn.setFixedSize(42, 42)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{ background: {_ORANGE}; color: #1a1a1a; font-size: 15px; font-weight: bold; border: none; border-radius: 2px; }}
            QPushButton:hover {{ background: {_ORANGE_HV}; }}
            QPushButton:disabled {{ background: {_BTN_BG}; color: {_TEXT_DIM}; }}
        """)
        self._send_btn.clicked.connect(self.send)
        il.addWidget(self._send_btn)
        root.addWidget(input_bar)

    # ── actions ───────────────────────────────────────────────────────────────

    def _set_key(self):
        key = self._key_input.text().strip()
        if key and ANTHROPIC_AVAILABLE:
            os.environ["ANTHROPIC_API_KEY"] = key
            self.client = anthropic.Anthropic(api_key=key)
            self._key_bar.hide()

    def _clear_chat(self):
        self.api_history.clear()
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def send(self):
        if not self.client:
            return
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self._send_btn.setEnabled(False)
        self._add_bubble("user", text)
        self.api_history.append({"role": "user", "content": text})
        self._set_thinking("  thinking…")
        threading.Thread(target=self._agent_loop, daemon=True).start()

    # ── agent loop (background thread) ───────────────────────────────────────

    def _agent_loop(self):
        import time
        delays = [2, 5, 10]

        # Cache the system prompt and tools schema — they're large and identical
        # across every call in a session. Cached tokens are ~10x faster to process.
        cached_system = [{"type": "text", "text": SYSTEM_PROMPT,
                          "cache_control": {"type": "ephemeral"}}]
        cached_tools = TOOLS[:-1] + [{**TOOLS[-1], "cache_control": {"type": "ephemeral"}}]

        while True:
            # Call API with retry on 529
            msg = None
            for attempt, delay in enumerate(delays + [None]):
                try:
                    msg = self.client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=cached_system,
                        tools=cached_tools,
                        messages=self.api_history,
                    )
                    break
                except Exception as exc:
                    code = getattr(getattr(exc, "response", None), "status_code", None)
                    if code == 529 and delay is not None:
                        self._response_signal.emit(f"_retry:{attempt + 1}:{delay}")
                        time.sleep(delay)
                    else:
                        self._response_signal.emit(f"Error: {exc}")
                        return

            if msg is None:
                self._response_signal.emit("Error: all retries failed")
                return

            if msg.stop_reason == "end_turn":
                blocks = [b for b in msg.content if hasattr(b, "text")]
                text = blocks[0].text if blocks else "(no response)"
                # Store as simple string for clean history
                self.api_history.append({"role": "assistant", "content": text})
                self._response_signal.emit(text)
                return

            elif msg.stop_reason == "tool_use":
                # Append assistant message (with tool_use blocks) to history
                self.api_history.append({"role": "assistant", "content": msg.content})

                tool_results = []
                for block in msg.content:
                    if block.type != "tool_use":
                        continue
                    self._tool_status_signal.emit(block.name)
                    if block.name == "call_houdini":
                        # HTTP call — must NOT run on main thread or it deadlocks
                        # with Houdini's web server. Run directly here in the bg thread.
                        result = self._call_fxhoudini(
                            block.input["command"],
                            block.input.get("params", {}),
                        )
                    else:
                        req = _ToolRequest(block.name, block.input)
                        self._tool_execute_signal.emit(req)
                        result = req.wait()
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(result),
                    })

                self.api_history.append({"role": "user", "content": tool_results})
                # Loop continues → send results back to Claude

            else:
                self._response_signal.emit(f"Unexpected stop_reason: {msg.stop_reason}")
                return

    # ── tool execution (main thread, called via signal) ───────────────────────

    def _on_tool_execute(self, req):
        result = self._run_tool(req.name, req.inputs)
        req.complete(result)

    @staticmethod
    def _run_tool(name, inputs):
        try:
            import hou
        except ImportError:
            return {"error": "hou not available"}

        try:
            if name == "scene_summary":
                obj = hou.node("/obj")
                children = obj.children() if obj else []
                return {
                    "obj_nodes": [{"name": n.name(), "type": n.type().name(), "path": n.path()} for n in children],
                    "current_frame": hou.frame(),
                    "frame_range": list(hou.playbar.frameRange()),
                }

            elif name == "list_children":
                node = hou.node(inputs["path"])
                if not node:
                    return {"error": f"Not found: {inputs['path']}"}
                return {"children": [{"name": c.name(), "type": c.type().name(), "path": c.path()} for c in node.children()]}

            elif name == "get_node_info":
                node = hou.node(inputs["path"])
                if not node:
                    return {"error": f"Not found: {inputs['path']}"}
                parms = {}
                for p in node.parms():
                    try:
                        parms[p.name()] = p.eval()
                    except Exception:
                        pass
                    if len(parms) >= 60:
                        break
                return {
                    "path":     node.path(),
                    "type":     node.type().name(),
                    "inputs":   [i.outputNode().path() if i and i.outputNode() else None for i in node.inputs()],
                    "outputs":  [o.path() for o in node.outputs()],
                    "parms":    parms,
                    "errors":   list(node.errors()),
                    "warnings": list(node.warnings()),
                }

            elif name == "list_node_types":
                cats = hou.nodeTypeCategories()
                ctx = inputs["context"]
                if ctx not in cats:
                    return {"error": f"Unknown context '{ctx}'. Available: {list(cats.keys())}"}
                filt = inputs.get("filter", "").lower()
                types = sorted(cats[ctx].nodeTypes().keys())
                if filt:
                    types = [t for t in types if filt in t.lower()]
                return {"types": types}

            elif name == "create_node":
                parent = hou.node(inputs["parent_path"])
                if not parent:
                    return {"error": f"Parent not found: {inputs['parent_path']}"}
                node = parent.createNode(inputs["node_type"], inputs.get("name"))
                return {"path": node.path(), "name": node.name(), "type": node.type().name()}

            elif name == "delete_node":
                node = hou.node(inputs["path"])
                if not node:
                    return {"error": f"Not found: {inputs['path']}"}
                node.destroy()
                return {"success": True}

            elif name == "set_parameter":
                node = hou.node(inputs["node_path"])
                if not node:
                    return {"error": f"Not found: {inputs['node_path']}"}
                parm = node.parm(inputs["parm_name"])
                if parm is None:
                    return {"error": f"Parm '{inputs['parm_name']}' not found on {inputs['node_path']}"}
                parm.set(inputs["value"])
                return {"success": True}

            elif name == "set_parameters":
                node = hou.node(inputs["node_path"])
                if not node:
                    return {"error": f"Not found: {inputs['node_path']}"}
                errors = []
                for pname, val in inputs["parms"].items():
                    parm = node.parm(pname)
                    if parm is None:
                        errors.append(f"parm '{pname}' not found")
                        continue
                    try:
                        parm.set(val)
                    except Exception as e:
                        errors.append(f"parm '{pname}': {e}")
                return {"success": True, "errors": errors} if not errors else {"partial": True, "errors": errors}

            elif name == "get_parameter":
                node = hou.node(inputs["node_path"])
                if not node:
                    return {"error": f"Not found: {inputs['node_path']}"}
                parm = node.parm(inputs["parm_name"])
                if parm is None:
                    return {"error": f"Parm '{inputs['parm_name']}' not found"}
                return {"value": parm.eval()}

            elif name == "connect_nodes":
                from_node = hou.node(inputs["from_path"])
                to_node   = hou.node(inputs["to_path"])
                if not from_node:
                    return {"error": f"From node not found: {inputs['from_path']}"}
                if not to_node:
                    return {"error": f"To node not found: {inputs['to_path']}"}
                to_node.setInput(inputs.get("input_index", 0), from_node, inputs.get("output_index", 0))
                return {"success": True}

            elif name == "find_errors":
                errors = []
                def _scan(node):
                    if node.errors():
                        errors.append({"path": node.path(), "errors": list(node.errors())})
                    for c in node.children():
                        _scan(c)
                _scan(hou.node("/"))
                return {"error_nodes": errors, "count": len(errors)}

            elif name == "run_python":
                ns = {"hou": hou, "__builtins__": __builtins__}
                exec(inputs["code"], ns)
                result = ns.get("_result", None)
                return {"success": True, "result": str(result) if result is not None else None}

            elif name == "call_houdini":
                return ClaudePanel._call_fxhoudini(inputs["command"], inputs.get("params", {}))

            else:
                return {"error": f"Unknown tool: {name}"}

        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _call_fxhoudini(command: str, params: dict) -> dict:
        """POST a command to Houdini's hwebserver plugin on localhost:8100."""
        import urllib.request
        import urllib.parse
        import uuid as _uuid

        body = urllib.parse.urlencode({
            "json": json.dumps(["mcp.execute", [], {
                "command": command,
                "params": params,
                "request_id": str(_uuid.uuid4()),
            }])
        }).encode()

        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8100/api",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            if isinstance(result, dict):
                if result.get("status") == "error":
                    return {"error": result.get("error", {}).get("message", "Unknown error")}
                if result.get("status") == "success":
                    return result.get("data", {})
            return result
        except Exception as exc:
            return {"error": str(exc)}

    # ── UI update slots (main thread) ─────────────────────────────────────────

    def _set_thinking(self, text):
        if not hasattr(self, "_thinking_lbl"):
            self._thinking_lbl = QtWidgets.QLabel()
            self._thinking_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-style: italic; padding: 2px 8px; background: transparent;")
            self._chat_layout.insertWidget(self._chat_layout.count() - 1, self._thinking_lbl)
        self._thinking_lbl.setText(text)
        self._thinking_lbl.show()
        self._scroll_bottom()

    def _show_tool_status(self, tool_name):
        self._set_thinking(f"  → {tool_name}…")

    def _show_response(self, text):
        if text.startswith("_retry:"):
            _, attempt, delay = text.split(":")
            self._set_thinking(f"  Anthropic overloaded — retrying ({attempt}/3) in {delay}s…")
            return

        if hasattr(self, "_thinking_lbl"):
            self._thinking_lbl.deleteLater()
            del self._thinking_lbl

        self._add_bubble("assistant", text)
        self._send_btn.setEnabled(True)
        self._scroll_bottom()

    def _add_bubble(self, role, content):
        bubble = MessageBubble(role, content)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        self._scroll_bottom()

    def _scroll_bottom(self):
        QtCore.QTimer.singleShot(60, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))


# ── Custom input widget (Enter = send, Shift+Enter = newline) ─────────────────

class _ChatInput(QtWidgets.QTextEdit):
    send_requested = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
        else:
            super().keyPressEvent(event)


def onCreateInterface():
    return ClaudePanel()
