"""Paint agentic-loop state onto the Houdini network editor.

Turns the network editor itself into the node-graph-diff widget by colouring
nodes the Editor touched, marking cook errors red, and tagging only our own
marks so artist colours stay intact.
"""
import hou

TOUCHED = hou.Color((0.25, 0.50, 1.00))   # blue  — changed this iteration
ERROR = hou.Color((0.90, 0.20, 0.20))     # red   — cook error
OK = hou.Color((0.27, 0.72, 0.31))        # green — touched, cooked clean
NEUTRAL = hou.Color((0.80, 0.80, 0.80))

_MARK = "loop_monitor_painted"            # only clear our own marks


def _touched_paths(iteration):
    """Node paths the Editor reports modifying — needs payload.node_path."""
    editor_event = None
    for e in iteration["events"]:
        if e.get("agent") == "editor":
            editor_event = e
    if not editor_event:
        return []
    return [a["node_path"]
            for a in editor_event.get("payload", {}).get("actions", [])
            if a.get("node_path")]


def clear_paint(root="/obj"):
    """Remove only marks this tool added — leave artist colours alone."""
    root_node = hou.node(root)
    if root_node is None:
        return
    for node in root_node.allSubChildren():
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
