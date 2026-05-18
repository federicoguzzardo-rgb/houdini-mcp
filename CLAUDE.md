# houdini-mcp

## Repository
- Name: houdini-mcp
- Root: C:\houdini
- Git: initialized at C:\houdini\.git

## Pipeline Context
- Software: SideFX Houdini 19.5.716
- Houdini Python: 3.9.10 (bundled hython)
- Renderer: Karma/RenderMan/Arnold (update as needed)
- Pipeline: USD/Solaris for look dev and lighting
- Asset format: HDAs for all reusable tools
- Cache format: .bgeo.sc for geometry, .vdb for volumes

## MCP Connection
- Server: fxhoudinimcp 1.0.0 (Python 3.12, uv tool)
- Source: https://github.com/healkeiser/fxhoudinimcp (vendored at C:\houdini\fxhoudinimcp)
- Executable: C:\Users\feder\.local\bin\fxhoudinimcp.exe
- Houdini host: 127.0.0.1:8100 (localhost only)
- Config: .mcp.json in project root
- Plugin: C:\Users\feder\OneDrive\Documents\houdini19.5\packages\fxhoudinimcp.json

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
- VEX: always declare types explicitly, use @attributes not detail() where possible
- Python: use hou module, target Houdini's bundled Python version (3.9.10)
- HDAs: version-lock all digital assets, never modify locked HDAs in production
- USD: follow ASWF naming conventions for prims and variants

## Workflow Rules
- Always work inside SOPs unless told otherwise
- Always check for cooking errors after node creation
- Take a viewport screenshot after any geometry operation to verify results
- Write VEX in wrangles, not inline — keeps networks readable
- Prefer VEX wrangles over Python for attribute operations
- Use @P, @N, @Cd attribute syntax in VEX
- Merge nodes before output nulls
- Prefer procedural approaches over hard-coded values
- Ask before deleting or overwriting any existing node network

## Session Behaviour
- Break complex tasks into checkpoints — confirm with a viewport screenshot at each
- If a cook error appears, stop and diagnose before continuing

## Task-Specific Specs
@.claude/procedural_sand_dune_hda.md
