# Houdini MCP + Claude Code — Session Handoff

## Goal
Control SideFX Houdini via Claude Code using MCP servers.

---

## What's Installed

### fxhoudinimcp (healkeiser)
- 168 tools across 19 categories
- Uses Houdini's built-in `hwebserver`
- Installed via `uv tool install fxhoudinimcp --python 3.12`
- Repo cloned from `github.com/healkeiser/fxhoudinimcp`
- Houdini plugin copied to packages directory

### oculairmedia/houdini-mcp
- 43 tools across 15 categories
- Uses `hrpyc` on port `18811`
- Separate implementation from fxhoudinimcp
- May have been installed in a prior session — verify status

### context-mode
- Token compression plugin
- Installed via `claude mcp add context-mode -- npx -y context-mode`
- Requires full Claude Code restart to activate

---

## Config Files Created

### `.mcp.json` (project root)
```json
{
  "mcpServers": {
    "fxhoudini": {
      "command": "python",
      "args": ["-m", "fxhoudinimcp"],
      "env": {
        "HOUDINI_HOST": "127.0.0.1",
        "HOUDINI_PORT": "8100"
      }
    }
  }
}
```
> `.mcp.json` is added to `.gitignore`

### `CLAUDE.md` (project root)
Full VFX pipeline context including:
- Pipeline stack (Houdini, Karma/USD/Solaris, HDAs, .bgeo.sc, .vdb)
- VEX coding rules (see below)
- Session behaviour rules (viewport screenshots, cook error checks, etc.)

---

## VEX Rules Baked into CLAUDE.md

Sourced from user's custom skill at `/mnt/skills/user/vex-houdini/SKILL.md`.

| Rule | Detail |
|---|---|
| Explicit type prefixes | `v@vel`, `i@id`, `f@mass`, `s@name` — never implicit float |
| Function declaration order | Must be declared BEFORE use — no recursion |
| No `turbulence()` | Manually accumulate `noise()` octaves |
| No `round()` | Use `rint()` instead |
| No `getprimitivebounds()` | Loop over vertices manually |
| No `primattrib()` | Use `prim(0, "attr_name", @primnum)` |
| Int division truncates | Always cast: `float(i) / float(n)` |
| `@uv` is vector3 | Access as `@uv.x`, `@uv.y` |
| `set()` builds vector3 | For vector2 use `{x, y}` literal |
| `removepoint()` in loops | Collect indices, remove after loop |
| `@P` in Volume Wrangle | Is voxel center, not a point |
| Channel refs | `chf()` float, `chi()` int, `chv()` vector, `chs()` string |
| LOPs/Solaris | Use `usd_attrib()` / `usd_setattrib()` — `@P`, `@Cd`, `@N` don't work |
| LOPs built-ins | `@primpath`, `@primtype`, `@primname` |

---

## Diagnostic Scripts

**Check fxhoudinimcp environment:**
```python
import os, sys
print("FXHOUDINIMCP =", os.environ.get("FXHOUDINIMCP", "NOT SET"))
print("Package path on sys.path:", any("fxhoudinimcp" in p for p in sys.path))
```

**Check Houdini prefs path:**
```python
import hou, os
print(hou.homeHoudiniDirectory())
print(os.environ.get("HOUDINI_USER_PREF_DIR", "NOT SET"))
```

---

## Current Status

| Item | Status |
|---|---|
| fxhoudinimcp installed | ✅ Done |
| Houdini plugin copied | ✅ Done |
| `.mcp.json` created | ✅ Done |
| `CLAUDE.md` created | ✅ Done |
| context-mode installed | ✅ Done |
| Claude Code restarted | ✅ Done |
| `ctx-doctor` verified | ✅ Done |
| Houdini launched | ✅ Done |
| MCP shelf tool activated | ✅ Done |
| `/mcp` connection verified | ✅ Done |
| All diagnostics passed | ✅ Done |
| Server running | ✅ Live |

> **Setup complete.** All tests and diagnostics passed. MCP server is live and ready for Houdini work.

---

## Key Repos

| Repo | URL | Stars | Notes |
|---|---|---|---|
| fxhoudinimcp | github.com/healkeiser/fxhoudinimcp | 3 | Primary — 168 tools |
| oculairmedia/houdini-mcp | github.com/oculairmedia/houdini-mcp | 18 | hrpyc — 43 tools, 418 tests |
| capoom/houdini-mcp | github.com/capoomgit/houdini-mcp | 54 | Original, most documented |
| context-mode | github.com/mksglu/context-mode | 14.1k | Token compression |
