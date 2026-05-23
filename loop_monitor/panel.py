"""In-Houdini Loop Monitor — Python Panel widget.

Approach B per loop-monitor-ui-brief.md §Approach B. Polls
runs/<run_id>/events.jsonl on a QTimer, never blocks the main thread, and
delegates network-editor painting to loop_monitor.graphpaint.

Imported by loop_monitor_panel.pypanel.
"""
import json
import sys
from pathlib import Path

import hou
from hou.qt import QtCore, QtWidgets

# Ensure `monitor/` is importable even when Houdini's PYTHONPATH doesn't
# include the repo root. Adjust HOUDINI_AGENTIC_ROOT in the .pypanel
# wrapper to point at the repo if you move it.
_REPO_ROOT = Path(hou.text.expandString(
    "$HOUDINI_AGENTIC_ROOT")) if hou.text.expandString(
        "$HOUDINI_AGENTIC_ROOT") else Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from monitor.eventlog import (  # noqa: E402
    read_events, group_by_iteration, latest_status,
    find_event, build_convergence_series,
)
from loop_monitor.graphpaint import paint_iteration, clear_paint  # noqa: E402

RUNS_DIR = _REPO_ROOT / "runs"
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
        self._chart = QtWidgets.QPlainTextEdit()  # TODO: QtCharts
        self._chart.setReadOnly(True)
        self._chart.setMaximumHeight(120)
        lay.addWidget(self._chart)

        lay.addWidget(QtWidgets.QLabel("Latest iteration"))
        self._detail = QtWidgets.QPlainTextEdit()
        self._detail.setReadOnly(True)
        lay.addWidget(self._detail)

        self._paint = QtWidgets.QCheckBox(
            "Paint loop state onto network editor")
        self._paint.setChecked(True)
        lay.addWidget(self._paint)

        clear_btn = QtWidgets.QPushButton("Clear paint")
        clear_btn.clicked.connect(lambda: clear_paint())
        lay.addWidget(clear_btn)

        if self._run_picker.count():
            self._select_run(self._run_picker.currentText())

    def _discover_runs(self):
        if not RUNS_DIR.exists():
            return []
        return sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir())

    def _select_run(self, run_id):
        if run_id:
            self._events_path = RUNS_DIR / run_id / "events.jsonl"
            self._poll()

    def _poll(self):
        # refresh the run picker in case new runs arrived
        runs = self._discover_runs()
        existing = [self._run_picker.itemText(i)
                    for i in range(self._run_picker.count())]
        if runs != existing:
            current = self._run_picker.currentText()
            self._run_picker.blockSignals(True)
            self._run_picker.clear()
            self._run_picker.addItems(runs)
            if current in runs:
                self._run_picker.setCurrentText(current)
            self._run_picker.blockSignals(False)

        if not self._events_path or not self._events_path.exists():
            return

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
