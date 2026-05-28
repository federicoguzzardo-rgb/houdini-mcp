"""Houdini shelf tool: copy current scene context to clipboard.

Press the shelf button, switch to Claude Desktop, paste, ask your question.
Gives Claude accurate scene awareness with zero API cost to discover state.
"""
import json
import subprocess
import hou


def _safe_eval(parm):
    try:
        return parm.eval()
    except Exception:
        return None


def gather_scene_context(max_nodes=4, max_parms=25):
    pwd = hou.pwd()

    # Network context type — drives which tools are relevant (Sop/Lop/Dop/...)
    try:
        ctx_type = pwd.childTypeCategory().name()
    except Exception:
        ctx_type = "unknown"

    selected = hou.selectedNodes()
    nodes = []
    for n in selected[:max_nodes]:
        parms = {}
        count = 0
        for p in n.parms():
            if count >= max_parms:
                break
            if p.isHidden() or p.isDisabled():
                continue
            val = _safe_eval(p)
            if val is not None:
                parms[p.name()] = val
                count += 1
        nodes.append({
            "path": n.path(),
            "type": n.type().name(),
            "errors": list(n.errors()),
            "warnings": list(n.warnings()),
            "parms": parms,
        })

    # Cook errors anywhere in the current network
    errored = []
    for child in pwd.children():
        if child.errors():
            errored.append(child.path())

    return {
        "network": pwd.path(),
        "context_type": ctx_type,
        "selected_nodes": nodes,
        "errored_nodes": errored or "none",
        "hip_file": hou.hipFile.basename(),
        "frame": int(hou.frame()),
    }


def _to_clipboard(text):
    # Windows
    try:
        subprocess.run("clip", input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        pass
    # Fallback: Qt clipboard (cross-platform, works inside Houdini)
    try:
        from hou.qt import QtWidgets
        QtWidgets.QApplication.clipboard().setText(text)
        return True
    except Exception:
        return False


def main():
    ctx = gather_scene_context()
    header = (
        "HOUDINI SCENE CONTEXT (paste-injected — current state of my session)\n"
        + json.dumps(ctx, indent=2)
        + "\n\nMy question: "
    )
    ok = _to_clipboard(header)
    msg = ("Scene context copied to clipboard.\n"
           "Switch to Claude Desktop, paste, and type your question after it."
           if ok else
           "Could not access clipboard — printing to console instead.")
    if not ok:
        print(header)
    hou.ui.displayMessage(msg, severity=hou.severityType.Message)


main()
