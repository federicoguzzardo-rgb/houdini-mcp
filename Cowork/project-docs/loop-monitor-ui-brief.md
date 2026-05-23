# Loop Monitor UI — Build Brief

> Feed this to Claude Code. It specifies **two interchangeable UIs** for
> monitoring the Houdini agentic loop. Both read the same event stream,
> so they are not mutually exclusive — Claude Code should pick the one
> that fits the current dev phase, or build the shared layer first and
> both on top of it.
>
> This is a spec, not finished code. Skeletons below are anchors; flesh
> out the `TODO`s.

---

## 0. Shared contract (build this first, regardless of UI choice)

Both UIs are **pure consumers** of `runs/<run_id>/events.jsonl`. They
import nothing from the agents and the agents import nothing from them.
The only coupling is the event envelope from project brief §14.

### Event envelope (recap)
```json
{
  "run_id": "uuid",
  "iteration": 4,
  "step_id": "4.2",
  "agent": "behavioral_critic",
  "event_type": "result",
  "timestamp": "2026-05-16T...",
  "duration_ms": 340,
  "payload": { }
}
```
Heavy artifacts (renders, graph snapshots) live on disk; the payload
carries a `*_ref` path only.

### `eventlog.py` — shared reader (used by BOTH UIs)
Single module, no Houdini and no Streamlit imports, so it works in any
process.

```python
"""Shared event-log reader. Imported by both the Streamlit and Houdini UIs."""
import json
from pathlib import Path
from collections import defaultdict


def read_events(path):
    """Parse events.jsonl. Tolerates a partial trailing line (live append)."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # incomplete write — skip, picked up next poll
    return out


def group_by_iteration(events):
    """-> {iteration_number: {'number': n, 'events': [...]}}"""
    grouped = defaultdict(lambda: {"number": None, "events": []})
    for e in events:
        n = e.get("iteration")
        if n is None:
            continue
        grouped[n]["number"] = n
        grouped[n]["events"].append(e)
    return dict(grouped)


def find_event(iteration, agent):
    """Last payload emitted by `agent` within an iteration bucket."""
    hits = [e for e in iteration["events"] if e.get("agent") == agent]
    return hits[-1]["payload"] if hits else {}


def latest_status(events):
    """Most recent convergence-judge decision + iteration count."""
    state, iteration = "running", 0
    for e in events:
        iteration = max(iteration, e.get("iteration", 0))
        if e.get("agent") == "convergence_judge":
            d = e.get("payload", {}).get("decision")
            state = {"done": "converged",
                     "stuck": "stuck",
                     "continue": "running"}.get(d, state)
    return {"state": state, "iteration": iteration}


def build_convergence_series(iters):
    """Rows for the intent_match / behavioral_pass_rate chart."""
    rows = []
    for n in sorted(iters):
        cj = find_event(iters[n], "convergence_judge")
        rows.append({
            "iteration": n,
            "intent_match": cj.get("intent_match"),
            "behavioral_pass_rate": cj.get("behavioral_pass_rate"),
        })
    return rows
```

### Design note for the Editor event schema
The Editor payload must carry an **explicit `node_path` string** per
action — not just the `call` expression. The in-Houdini UI needs it to
resolve nodes, and per `fetched-sources.md §9` the orchestrator should
use path strings (not `hou` proxy objects) anyway because of the
`hrpyc` `__eq__` limitation. Bake this into the Editor from the start:

```json
// Editor payload — add node_path
{ "actions": [
    {"node_path": "/obj/geo1/box1",
     "call": "box1.parm('sizey').set(1.3)",
     "result": "ok", "before": 1.0, "after": 1.3}] }
```

---

## Approach A — Streamlit Dashboard

**Use when:** the loop reliably completes ≥3 iterations end-to-end and
you want to *study convergence* — timeline, charts, side-by-side
critique. External to Houdini; survives Houdini restarts.

**Don't use when:** still debugging bridge timeouts / malformed JSON —
`tail -f events.jsonl | jq` beats a GUI for that phase.

### File layout
```
monitor/
  eventlog.py        # shared, from §0
  app.py             # Streamlit entrypoint
```

### `app.py` — skeleton
```python
"""
Loop Monitor — Streamlit dashboard.
Run:  streamlit run app.py -- --run-id brick-wall-03
"""
import argparse
from pathlib import Path
import streamlit as st

from eventlog import (read_events, group_by_iteration, latest_status,
                      find_event, build_convergence_series)

RUNS_DIR = Path("runs")
REFRESH_SECONDS = 2

st.set_page_config(page_title="Loop Monitor", layout="wide")


def get_run_id():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default=None)
    args, _ = p.parse_known_args()
    return args.run_id


def it_colour(it):
    """green=converged, red=behavioral fail, amber=in vlm stage."""
    bc = find_event(it, "behavioral_critic")
    cj = find_event(it, "convergence_judge")
    if cj.get("decision") == "done":
        return "#3fb950"
    if bc and not bc.get("passed", True):
        return "#f85149"
    return "#d29922"


run_id = get_run_id() or st.sidebar.selectbox(
    "Run", sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir()))
events_path = RUNS_DIR / run_id / "events.jsonl"


@st.fragment(run_every=REFRESH_SECONDS)          # re-runs only this block
def dashboard():
    events = read_events(events_path)
    iters = group_by_iteration(events)
    status = latest_status(events)

    # --- header ---
    c1, c2, c3 = st.columns(3)
    c1.metric("Run", run_id)
    c2.metric("Status", status["state"])
    c3.metric("Iteration", status["iteration"])

    # --- timeline (clickable cells, colour-coded) ---
    st.subheader("Timeline")
    cols = st.columns(max(len(iters), 1))
    for col, n in zip(cols, sorted(iters)):
        if col.button(str(n), key=f"cell{n}"):
            st.session_state.selected = n
        col.markdown(
            f"<div style='height:6px;background:{it_colour(iters[n])}'></div>",
            unsafe_allow_html=True)

    # --- convergence chart (the highest-value widget) ---
    st.subheader("Convergence")
    st.line_chart(build_convergence_series(iters),
                  x="iteration",
                  y=["intent_match", "behavioral_pass_rate"])

    # --- iteration detail ---
    sel = st.session_state.get("selected", max(iters) if iters else None)
    if sel is not None:
        render_detail(iters[sel])


def render_detail(it):
    st.subheader(f"Iteration {it['number']}")
    left, mid, right = st.columns([2, 2, 2])

    # composed observation render (PNG already on disk via *_ref)
    obs = find_event(it, "vlm_critic").get("observation_ref")
    if obs and Path(obs).exists():
        left.image(obs, caption="composed observation")

    with mid:
        st.markdown("**Behavioral**");  st.json(find_event(it, "behavioral_critic"))
        st.markdown("**VLM critique**"); st.json(find_event(it, "vlm_critic"))
    with right:
        st.markdown("**Translator**");   st.json(find_event(it, "translator"))
        st.markdown("**Editor log**");   st.json(find_event(it, "editor"))
    # TODO: node-graph diff panel — asked-for (translator.actions)
    #       vs actually-changed (editor.actions). This gap is where bugs live.


dashboard()
```

### Build scope
- **In:** timeline, convergence chart, iteration detail, run picker, auto-refresh.
- **Defer:** draggable timeline scrubber, the "edit feedback" stepping
  control (§13 of brief) — add only once the basic monitor is trusted.
- **Graduate to React + FastAPI** only when real-time streaming or the
  scrubber are genuinely wanted.

---

## Approach B — In-Houdini Python Panel

**Use when:** you want loop state *next to the node graph* and the
**network editor itself** acting as the node-graph diff — nodes coloured
by what the Editor touched and what threw cook errors. TD-native; zero
extra windows.

**Don't use when:** you need the monitor to outlive a Houdini crash, or
to watch a headless `hython` run with no GUI.

### File layout
```
monitor/
  eventlog.py                  # shared, from §0
loop_monitor/
  __init__.py
  panel.py                     # the Qt widget
  graphpaint.py                # network-editor node colouring
loop_monitor_panel.pypanel     # thin XML wrapper Houdini registers
```
Put `monitor/` and `loop_monitor/` on Houdini's `PYTHONPATH`
(e.g. `$HOUDINI_USER_PREF_DIR/python3.x/libs`, or a houdini package json).

### `loop_monitor_panel.pypanel` — XML wrapper
Keep this thin; all real code lives in `panel.py` so it's editable
without the Python Panel editor.
```xml
<?xml version="1.0" encoding="UTF-8"?>
<pythonPanelDocument>
  <interface name="loop_monitor" label="Loop Monitor"
             icon="MISC_python" help_url="">
    <script><![CDATA[
import importlib
import loop_monitor.panel as panel
importlib.reload(panel)          # dev convenience: pick up edits on reopen

def onCreateInterface():
    return panel.LoopMonitorPanel()
]]></script>
    <help><![CDATA[Tails runs/<run_id>/events.jsonl; paints loop state on the graph.]]></help>
  </interface>
</pythonPanelDocument>
```

### `loop_monitor/panel.py` — skeleton
Use `hou.qt` (not a direct `PySide2`/`PySide6` import) so it survives
Houdini version changes. Poll with a `QTimer` — never block Houdini's
main thread.
```python
"""In-Houdini Loop Monitor — Python Panel widget."""
import json
from pathlib import Path

import hou
from hou.qt import QtCore, QtWidgets

from eventlog import (read_events, group_by_iteration, latest_status,
                      find_event, build_convergence_series)
from loop_monitor.graphpaint import paint_iteration, clear_paint

RUNS_DIR = Path(hou.text.expandString("$HIP")) / "runs"
POLL_MS = 2000


class LoopMonitorPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._events_path = None
        self._build_ui()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)

        self._run_picker = QtWidgets.QComboBox()
        self._run_picker.addItems(self._discover_runs())
        self._run_picker.currentTextChanged.connect(self._select_run)
        lay.addWidget(self._run_picker)

        self._status = QtWidgets.QLabel("—")
        lay.addWidget(self._status)

        lay.addWidget(QtWidgets.QLabel("Convergence"))
        self._chart = QtWidgets.QPlainTextEdit(readOnly=True)   # TODO: QtCharts
        self._chart.setMaximumHeight(120)
        lay.addWidget(self._chart)

        lay.addWidget(QtWidgets.QLabel("Latest iteration"))
        self._detail = QtWidgets.QPlainTextEdit(readOnly=True)
        lay.addWidget(self._detail)

        self._paint = QtWidgets.QCheckBox(
            "Paint loop state onto network editor", checked=True)
        lay.addWidget(self._paint)

        if self._run_picker.count():
            self._select_run(self._run_picker.currentText())

    def _discover_runs(self):
        return (sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir())
                if RUNS_DIR.exists() else [])

    def _select_run(self, run_id):
        if run_id:
            self._events_path = RUNS_DIR / run_id / "events.jsonl"
            self._poll()

    def _poll(self):
        if not self._events_path or not self._events_path.exists():
            return
        # full re-read is fine at dev scale; switch to byte-offset
        # incremental read if events.jsonl grows large
        events = read_events(self._events_path)
        iters = group_by_iteration(events)
        status = latest_status(events)

        self._status.setText(
            f"{status['state']}  ·  iteration {status['iteration']}")
        self._chart.setPlainText("\n".join(
            f"it {r['iteration']:>2}  intent={r['intent_match']}  "
            f"behav={r['behavioral_pass_rate']}"
            for r in build_convergence_series(iters)))

        if iters:
            last = iters[max(iters)]
            self._detail.setPlainText(self._format(last))
            if self._paint.isChecked():
                paint_iteration(last)

    @staticmethod
    def _format(it):
        parts = []
        for agent in ("behavioral_critic", "vlm_critic",
                      "translator", "editor", "convergence_judge"):
            p = find_event(it, agent)
            if p:
                parts.append(f"[{agent}]\n{json.dumps(p, indent=2)}")
        return "\n\n".join(parts)
```

### `loop_monitor/graphpaint.py` — the genuinely Houdini-native bit
Turns the network editor itself into the node-graph diff widget.
```python
"""Paint agentic-loop state onto the Houdini network editor."""
import hou

TOUCHED = hou.Color((0.25, 0.50, 1.00))   # blue  — changed this iteration
ERROR   = hou.Color((0.90, 0.20, 0.20))   # red   — cook error
OK      = hou.Color((0.27, 0.72, 0.31))   # green — touched, cooked clean
NEUTRAL = hou.Color((0.80, 0.80, 0.80))

_MARK = "loop_monitor_painted"            # so we only clear our own marks


def _touched_paths(iteration):
    """Node paths the Editor reports modifying — needs payload.node_path."""
    editor = find := None
    for e in iteration["events"]:
        if e.get("agent") == "editor":
            editor = e
    if not editor:
        return []
    return [a["node_path"]
            for a in editor.get("payload", {}).get("actions", [])
            if a.get("node_path")]


def clear_paint(root="/obj"):
    """Remove only marks this tool added — leave artist colours alone."""
    for node in hou.node(root).allSubChildren():
        if node.userData(_MARK):
            node.setColor(NEUTRAL)
            node.destroyUserData(_MARK, must_exist=False)


def paint_iteration(iteration, root="/obj"):
    clear_paint(root)
    for path in set(_touched_paths(iteration)):
        node = hou.node(path)
        if node is None:
            continue
        node.setColor(ERROR if node.errors() else OK)
        node.setUserData("nodeshape", "circle")   # extra visual diff marker
        node.setUserData(_MARK, "1")
```

### Registration steps (for the user, after Claude Code builds it)
1. Place `monitor/` and `loop_monitor/` on Houdini's `PYTHONPATH`.
2. `Windows > Python Panel Editor` → gear menu → import
   `loop_monitor_panel.pypanel`.
3. Add a pane tab: pane menu → `New Pane Tab Type > Python Panel >
   Loop Monitor`. Dock it beside the Network Editor.

### Build scope
- **In:** run picker, status, text convergence list, iteration detail,
  network-editor painting toggle.
- **Defer:** replace the `QPlainTextEdit` convergence list with a real
  `QtCharts` line chart; incremental byte-offset tailing.

---

## Decision matrix — let Claude Code choose

| Factor | Streamlit (A) | In-Houdini Panel (B) |
|---|---|---|
| Setup cost | low — one `app.py` | medium — `.pypanel` + PYTHONPATH wiring |
| Survives Houdini crash/restart | yes | no |
| Works for headless `hython` runs | yes | no |
| Node-graph diff | separate widget (TODO) | **the network editor itself** |
| Charts | native `st.line_chart` | needs QtCharts (deferred) |
| Lives next to the node graph | no | yes |
| Best dev phase | loop completes ≥3 iters, studying convergence | interactive Houdini sessions, graph-level debugging |

**Recommended order if building both:**
1. `eventlog.py` (§0) — shared, mandatory either way.
2. Streamlit (A) — fastest to a working monitor; covers headless runs.
3. In-Houdini panel (B) — add when graph-level debugging is wanted;
   reuses `eventlog.py` unchanged.

The two are not exclusive — same event stream, so both can run at once.
