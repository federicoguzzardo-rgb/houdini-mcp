"""
Loop Monitor — Streamlit dashboard.
Run:  streamlit run monitor/app.py -- --run-id mock-01
"""
import argparse
import sys
from pathlib import Path

import streamlit as st

# allow `streamlit run monitor/app.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.eventlog import (
    read_events, group_by_iteration, latest_status,
    find_event, build_convergence_series,
)

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"
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


def _list_runs():
    if not RUNS_DIR.exists():
        return []
    return sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir())


cli_run = get_run_id()
runs = _list_runs()
if not runs:
    st.warning("No runs found in runs/. Generate one via `python scripts/mock_run.py`.")
    st.stop()

default_idx = runs.index(cli_run) if cli_run in runs else len(runs) - 1
run_id = st.sidebar.selectbox("Run", runs, index=default_idx)

events_path = RUNS_DIR / run_id / "events.jsonl"


def _graph_diff_rows(it):
    """Side-by-side rows: asked-for (translator) vs actually-changed (editor)."""
    tr = find_event(it, "translator").get("actions", []) or []
    ed = find_event(it, "editor").get("actions", []) or []
    asked = {a.get("node") or a.get("node_path"): a for a in tr}
    done = {a.get("node_path"): a for a in ed}
    keys = sorted(set(asked) | set(done))
    rows = []
    for k in keys:
        a, d = asked.get(k, {}), done.get(k, {})
        rows.append({
            "node": k,
            "asked_parm": a.get("parm", ""),
            "asked_change": a.get("change", ""),
            "actual_call": d.get("call", ""),
            "before": d.get("before", ""),
            "after": d.get("after", ""),
            "result": d.get("result", ""),
        })
    return rows


@st.fragment(run_every=REFRESH_SECONDS)
def dashboard():
    events = read_events(events_path)
    iters = group_by_iteration(events)
    status = latest_status(events)

    c1, c2, c3 = st.columns(3)
    c1.metric("Run", run_id)
    c2.metric("Status", status["state"])
    c3.metric("Iteration", status["iteration"])

    st.subheader("Timeline")
    if iters:
        cols = st.columns(len(iters))
        for col, n in zip(cols, sorted(iters)):
            if col.button(str(n), key=f"cell{n}"):
                st.session_state.selected = n
            col.markdown(
                f"<div style='height:6px;background:{it_colour(iters[n])}'></div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No iterations yet.")

    st.subheader("Convergence")
    series = [r for r in build_convergence_series(iters)
              if r["intent_match"] is not None
              or r["behavioral_pass_rate"] is not None]
    if series:
        st.line_chart(series, x="iteration", y=["intent_match", "behavioral_pass_rate"])

    # Default selection prefers iterations the convergence judge actually
    # weighed in on; orphan iterations (e.g. post-validation, manual hython
    # runs) do not become the implicit "latest" view.
    judged = [n for n in iters
              if find_event(iters[n], "convergence_judge")]
    default_sel = max(judged) if judged else (max(iters) if iters else None)
    sel = st.session_state.get("selected", default_sel)
    if sel is not None and sel in iters:
        render_detail(iters[sel])


def render_detail(it):
    st.subheader(f"Iteration {it['number']}")
    left, mid, right = st.columns([2, 2, 2])

    obs = find_event(it, "vlm_critic").get("observation_ref")
    if obs and Path(obs).exists():
        left.image(obs, caption="composed observation")
    else:
        left.caption("(no observation render)")

    with mid:
        st.markdown("**Behavioral**"); st.json(find_event(it, "behavioral_critic"))
        st.markdown("**VLM critique**"); st.json(find_event(it, "vlm_critic"))
    with right:
        st.markdown("**Translator**"); st.json(find_event(it, "translator"))
        st.markdown("**Editor log**"); st.json(find_event(it, "editor"))

    st.markdown("**Node-graph diff — asked-for vs actually-changed**")
    rows = _graph_diff_rows(it)
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.caption("(no actions in this iteration)")


dashboard()
