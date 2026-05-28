# houdini-mcp — Interactive Collaborator

## What this is
An in-scene Houdini collaborator. Claude Desktop (Pro subscription) connects to
the running Houdini via the fxhoudini MCP bridge and helps interactively, one
task per conversation. NOT an autonomous loop — the user triggers each task.

## Client
- Claude Desktop app (flat Pro rate). NOT Claude Code CLI (API billing).
- MCP config: `%APPDATA%\Claude\claude_desktop_config.json`
- **No `ANTHROPIC_API_KEY` in environment** — if set, tools silently bill the API
  instead of the subscription. Check shell profile and Windows environment variables.

## Bridge (unchanged, working)
- fxhoudinimcp 1.0.0 (Python 3.12, uv tool)
- Source: https://github.com/healkeiser/fxhoudinimcp (vendored at C:\houdini\fxhoudinimcp)
- Executable: `C:\Users\feder\.local\bin\fxhoudinimcp.exe`
- Houdini host: 127.0.0.1:8100 (localhost only)
- Config: `.mcp.json` in project root
- Plugin: `C:\Users\feder\OneDrive\Documents\houdini19.5\packages\fxhoudinimcp.json`

## Workflow
1. In Houdini, press **"Copy Context for Claude"** shelf tool (`tools/context_injector.py`).
2. Switch to Claude Desktop, paste, type your question after the context block.
3. Claude inspects, changes, checks errors, screenshots, iterates, and reports.
4. Confirm or redirect.

## Tools
- `tools/context_injector.py` — shelf tool: scene state → clipboard (install once as a Houdini shelf tool)
- `agents/behavioral_checks.py` — optional deterministic validity sweep (no LLM, runs inside Houdini via `code.execute_python`)
- `agents/_archive/` — the old autonomous orchestrator (parked, not deleted)

## Pipeline
- Software: SideFX Houdini 19.5.716, Python 3.9.10 (bundled hython)
- Renderer: Karma/RenderMan/Arnold
- Pipeline: USD/Solaris for look dev and lighting
- Asset format: HDAs for all reusable tools
- Cache format: .bgeo.sc for geometry, .vdb for volumes

## Scene Structure
- Main geometry: /obj/geo1
- Render ROP: /out/mantra1
- Output path: C:/renders/
- Frame range: 1001-1100

## Naming Conventions
- Geometry nodes: geo_[name]
- Null nodes: OUT_[name]
- Groups: grp_[name]

## Coding Standards
- VEX: always declare types explicitly (`v@vel`, `i@id`, `f@mass`, `s@name`); bare `@` makes a float
- VEX: no `turbulence()` — accumulate `noise()` octaves manually; use `rint()` not `round()`
- VEX: LOPs — use `usd_attrib()` / `usd_setattrib()` and `@primpath` / `@primtype`; `@P/@Cd/@N` don't work
- Python: use hou module, target Houdini's bundled Python version (3.9.10)
- HDAs: version-lock all digital assets, never modify locked HDAs in production
- USD: follow ASWF naming conventions for prims and variants

## Workflow Rules
- Always work inside SOPs unless told otherwise
- Always check for cooking errors after node creation
- Take a viewport screenshot after any geometry operation to verify results
- Write VEX in wrangles, not inline — keeps networks readable
- Prefer VEX wrangles over Python for attribute operations
- Merge nodes before output nulls
- Prefer procedural approaches over hard-coded values
- Ask before deleting or overwriting any existing node network

## Session Behaviour
- If a "HOUDINI SCENE CONTEXT" block is pasted, trust it as current state — skip rediscovery
- Make the smallest change that achieves the goal
- After any geometry change: check cook errors before reporting success
- After geometry looks complete: capture a viewport screenshot and judge against intent
- If a cook error appears, stop and diagnose before continuing
- Stop when cook is clean AND result matches the request; then report what changed and which parameters are worth exposing

## Knowledge Graph (Understand Anything)
- Plugin: understand-anything 2.7.4 (Claude Code plugin)
- Graph: `C:\houdini\.understand-anything\knowledge-graph.json`
- Run `/understand` to rebuild or incrementally update the graph after code changes
- Run `/understand-dashboard` to launch the interactive graph viewer
- Run `/understand-anything:understand-chat` to ask questions about the codebase
- Note: if a file is deleted but not yet committed, prune it manually from the graph
- Dashboard needs the token URL printed by Vite — always use the `?token=` param
- pnpm-workspace.yaml has `allowBuilds: true` for all tree-sitter packages (required for plugin build)
