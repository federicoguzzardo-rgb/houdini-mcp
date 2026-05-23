"""Behavioral check primitives — pure logic, hou-only.

Imported by both:
  - agents/behavioral_critic_runner.py (hython subprocess, headless)
  - agents/behavioral_critic.py "live" mode (sent over the wire to
    fxhoudinimcp's code.execute_python and run in the GUI Houdini)

`hou` is imported at function call sites, not at module top — so the source
of this file can be read as text and shipped over the wire without the
orchestrator (which has no hou) needing to import it.

Implements project brief §7:
  1. Structural invariants (manifold, degenerate prims, NaN positions,
     nonzero geo)
  2. Parametric sweeps: N=5 samples across each exposed parm range
  3. Frame sweeps if time-dependent

Public entrypoint: `evaluate(node_path, parm_sweep, samples=5)` returns
the typed JSON payload defined by project brief §14.

NB: deliberately avoids `from __future__ import annotations` so the source
can be concatenated after a runtime bootstrap when shipped via
fxhoudinimcp's code.execute_python.
"""


def _sample_range(lo, hi, n=5):
    if hi <= lo:
        return [lo]
    step = (hi - lo) / (n - 1)
    return [lo + i * step for i in range(n)]


def structural_checks(geo) -> list:
    """Manifold / degenerate / NaN / nonzero. Returns one row per check."""
    out = []

    has_geo = geo.intrinsicValue("primitivecount") > 0
    out.append({"check": "nonzero_geo", "passed": bool(has_geo)})

    nan_count = 0
    for pt in geo.points():
        p = pt.position()
        if any((c != c) for c in (p.x(), p.y(), p.z())):  # NaN != NaN
            nan_count += 1
    out.append({"check": "nan_positions", "passed": nan_count == 0,
                "nan_count": nan_count})

    degenerate = 0
    for prim in geo.prims():
        try:
            if len(prim.vertices()) < 3:
                degenerate += 1
        except Exception:
            degenerate += 1
    out.append({"check": "degenerate_prims", "passed": degenerate == 0,
                "degenerate_count": degenerate})

    try:
        non_manifold = geo.intrinsicValue("nonmanifold_edge_count")
    except Exception:
        non_manifold = 0
    out.append({"check": "manifold", "passed": (non_manifold or 0) == 0,
                "nonmanifold_edge_count": non_manifold})

    return out


def parametric_sweep(node, parm_names, samples=5):
    import hou
    rows = []
    for name in parm_names:
        parm = node.parm(name)
        if parm is None:
            rows.append({"parm": name, "passed": False,
                         "error": "parameter not found"})
            continue

        template = parm.parmTemplate()
        try:
            lo, hi = template.minValue(), template.maxValue()
        except AttributeError:
            lo, hi = 0.1, 5.0  # fallback for parms without explicit range

        # Box-size-style parms often have min=-1; sweep the positive half
        # only when both ends are non-negative useful values.
        if hi <= 0:
            lo, hi = 0.1, 5.0

        original = parm.eval()
        try:
            for v in _sample_range(lo, hi, samples):
                parm.set(v)
                try:
                    node.cook(force=True)
                    g = node.geometry()
                    if g is None or g.intrinsicValue("primitivecount") == 0:
                        rows.append({"parm": name, "value": v,
                                     "passed": False, "error": "empty output"})
                    else:
                        rows.append({"parm": name, "value": v, "passed": True})
                except hou.OperationFailed as e:
                    rows.append({"parm": name, "value": v,
                                 "passed": False, "error": str(e)})
        finally:
            parm.set(original)
            try:
                node.cook(force=True)
            except Exception:
                pass
    return rows


def frame_sweep(node, frames=(1, 12, 24)):
    import hou
    if not node.isTimeDependent():
        return []
    rows = []
    original_frame = hou.frame()
    try:
        for f in frames:
            hou.setFrame(f)
            try:
                node.cook(force=True)
                rows.append({"frame": f, "passed": True})
            except Exception as e:
                rows.append({"frame": f, "passed": False, "error": str(e)})
    finally:
        hou.setFrame(original_frame)
    return rows


def evaluate(node_path, parm_sweep, samples=5):
    """Project brief §7 entrypoint. Returns the typed payload."""
    import hou
    node = hou.node(node_path)
    if node is None:
        return {
            "passed": False, "node_path": node_path,
            "structural": [], "parametric": [], "frame_sweep": [],
            "error": f"node not found: {node_path}",
        }

    try:
        node.cook(force=True)
    except Exception as e:
        return {
            "passed": False, "node_path": node_path,
            "structural": [], "parametric": [], "frame_sweep": [],
            "error": f"initial cook failed: {e}",
        }

    geo = node.geometry()
    structural = (structural_checks(geo) if geo is not None
                  else [{"check": "geometry_present", "passed": False}])
    structural_ok = all(c["passed"] for c in structural)

    parametric = (parametric_sweep(node, parm_sweep, samples)
                  if structural_ok and parm_sweep else [])
    parametric_ok = all(p.get("passed") for p in parametric)

    fsweep = frame_sweep(node) if structural_ok else []
    frame_ok = all(p.get("passed") for p in fsweep)

    return {
        "passed": structural_ok and parametric_ok and frame_ok,
        "node_path": node_path,
        "structural": structural,
        "parametric": parametric,
        "frame_sweep": fsweep,
    }
