# C:\houdini — Context Overview

> Master reference for the Houdini Agentic System project.
> Covers project goal, workspace layout, repos, MCP bridges, architecture, and quick-start notes.

---

## 1. Project Goal

Build an agentic system that controls **SideFX Houdini** to produce procedural 3D content from natural-language instructions. The research focus is the **feedback loop** — how a critic evaluates Houdini output and turns that evaluation into corrective action — rather than generation itself.

Three SIGGRAPH 2025 papers (MatCLIP, BuildingBlock, EditDuet) seeded the architecture. The closest existing system is threedle/LL3M (Blender). No published system targets Houdini's procedural node-graph + VEX paradigm — that gap is the project's differentiation.

---

## 2. Workspace Layout — `C:\houdini\Cowork`

```
Cowork/
├── INSTRUCTIONS.md          ← this file
├── project-docs/            ← knowledge base (4 design docs)
│   ├── houdini-agentic-system-project-brief.md   ← full architecture spec
│   ├── fetched-sources.md                        ← annotated research fetch
│   ├── houdini_mcp_handoff.md                    ← MCP install & config notes
│   └── loop-monitor-ui-brief.md                  ← loop monitor UI spec (Streamlit + in-Houdini panel)
├── houdini-mcp/             ← oculairmedia bridge (hrpyc, 43 tools)
├── fxhoudinimcp/            ← healkeiser bridge (hwebserver, 168 tools) ← INSTALLED
├── ll3m/                    ← threedle Blender reference (architecture template)
└── GPTEval3D/               ← 3DTopia VLM pairwise eval (CVPR 2024)
```

---

## 3. MCP Bridges

Two MCP servers connect Claude / agent orchestrators to a live Houdini session.

### 3.1 fxhoudinimcp (healkeiser) — PRIMARY / INSTALLED
- **Transport:** Houdini's built-in `hwebserver` on **port 8100**
- **Scale:** 168 tools, 8 resources, 6 workflow prompts across 19 categories
- **Install:** `uv tool install fxhoudinimcp --python 3.12`
- **Houdini plugin:** copied to packages directory; starts automatically
- **MCP config (`.mcp.json`):**
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
- **Tool categories:** Scene, Nodes, Parameters, Geometry/SOPs, LOPs/USD, DOPs, PDG/TOPs, COPs, HDAs, Animation, Rendering, VEX, Code Execution, Viewport/UI, Workflows, Materials, CHOPs

**Key server files:**
```
fxhoudinimcp/
├── python/fxhoudinimcp/          ← MCP client-side (bridge.py, _loader.py)
└── houdini/scripts/python/fxhoudinimcp_server/
    ├── hwebserver_app.py         ← HTTP server entry point
    ├── dispatcher.py             ← routes requests to handlers
    └── handlers/                 ← one file per context
        ├── node_handlers.py
        ├── geometry_handlers.py
        ├── lops_handlers.py
        ├── vex_handlers.py
        ├── rendering_handlers.py
        └── ... (14 more)
```

### 3.2 houdini-mcp (oculairmedia) — SECONDARY / REFERENCE
- **Transport:** `hrpyc` on **port 18811** (RPyC-based, direct `hou` object access)
- **Scale:** 43 tools across 15 categories, 418 tests
- **Two modes:**
  - **stdio** — `hython` runs the MCP server inside Houdini directly
  - **Docker/remote** — MCP server in Docker connects to Houdini via hrpyc; exposes HTTP on port 3055
- **Start hrpyc in Houdini:**
  ```python
  import hrpyc
  hrpyc.start_server(port=18811)
  ```
- **Key limitation:** rpyc proxy objects don't support `__eq__`/`__hash__` — always use `.path()` strings for node identity

**Tool categories:** scene, nodes, wiring, layout, parameters, geometry, materials, rendering, pane screenshots, code execution, hscript, errors, help, summarization, cache

**Key server files:**
```
houdini-mcp/
├── houdini_mcp/
│   ├── server.py          ← FastMCP server, 43 tool wrappers
│   ├── connection.py      ← RPyC connection, retry/backoff
│   └── tools/             ← modular tool implementations
├── houdini_plugin/        ← Houdini plugin for stdio mode
├── examples/              ← 4 working workflow scripts
└── tests/                 ← 418 tests (406 passing)
```

### 3.3 Bridge Decision
| Use case | Bridge |
|---|---|
| Day-to-day MCP tool calls | **fxhoudinimcp** (installed, 168 tools) |
| Agent orchestrator needing direct `hou` access | **hrpyc** via houdini-mcp |
| Headless behavioral critic parametric sweeps | `hython` (no GUI) |

---

## 4. Reference Repos

### 4.1 ll3m (threedle) — Blender Agentic System
**License:** Academic/Evaluation only

The primary architectural reference. Closest existing system to this project — multi-agent Blender control with visual critique.

```
ll3m/
├── main.py              ← orchestrator (1172 lines), loop phases
├── blender/
│   ├── addon.py         ← Blender HTTP server on port 8888
│   ├── client.py        ← BlenderClient (execute_code, render_scene)
│   └── headless.py      ← headless render → PNG
├── config/config.yaml   ← model/phase config
└── utils/               ← feedback, signals, timer
```

**Loop phases:** `initial_creation` → `auto_refinement` → `user_guided_refinement`

**Error heuristic (weak — the gap we improve):** string match on `"error:"`, `"traceback"`, `"failed"` in execution result.

**Houdini port mapping:**
| LL3M (Blender) | Our project (Houdini) |
|---|---|
| `addon.py` HTTP server port 8888 | `hwebserver` port 8100 or `hrpyc` port 18811 |
| `BlenderClient.execute_code()` | `hou` calls via hrpyc or fxhoudinimcp |
| Headless render → PNG | `hython` batch cook + opengl/karma ROP |
| `.blend` snapshot | `.hip` snapshot |

### 4.2 GPTEval3D (3DTopia) — VLM Pairwise Evaluator
**Paper:** arxiv.org/abs/2401.04092 (CVPR 2024)

```
GPTEval3D/
├── gpt_eval_alpha.py              ← main evaluation script
├── utils/
│   ├── gpt4v_utils.py             ← GPT-4V pairwise comparison logic
│   ├── glide_elo.py               ← Elo rating computation
│   ├── t23d_tournament.py         ← tournament runner
│   └── image_utils.py             ← multi-view image prep
└── data/tournament-v0/
    ├── config.json
    ├── prompts.json
    └── gpt_prompts/               ← prompt templates (n1, n4, n9 views)
```

**Key design:** pairwise > absolute scoring. 120 evenly-spaced view renders per asset fed to GPT-4V → Elo ratings. Our adaptation uses 4-view package (front/side/top/persp + wireframe).

---

## 5. Agentic Architecture

```
NL Prompt
    │
    ▼
┌──────────────┐
│  Orchestrator │  manages loop state, graph backtracking
└──────┬───────┘
       │
       ├──► Translator        perception → action (separate roles, no collapse)
       │
       ├──► Editor            executes targeted node changes via MCP
       │        └── fxhoudinimcp / hrpyc → Houdini
       │
       ├──► Behavioral Critic  parametric sweep tests via hython (headless)
       │        └── typed JSON critique, catches silent failures
       │
       ├──► VLM Critic         4-view render → GPT-4V pairwise comparison
       │        └── GPTEval3D pattern; gated after behavioral pass
       │
       └──► Convergence Judge  intent_match scalar + behavioral_pass_rate
                └── decision: "continue" | "done" | "stuck"
```

**Event envelope** (written to `runs/<run_id>/events.jsonl`):
```json
{
  "run_id": "uuid",
  "iteration": 4,
  "step_id": "4.2",
  "agent": "behavioral_critic",
  "event_type": "result",
  "timestamp": "2026-...",
  "duration_ms": 340,
  "payload": {}
}
```

Heavy artifacts (renders, graph snapshots) live on disk; payload carries `*_ref` path only.

---

## 6. Loop Monitor UI

Two interchangeable UIs, both consuming `runs/<run_id>/events.jsonl`. Shared reader module `eventlog.py` is the foundation of both.

**Approach A — Streamlit dashboard** (`monitor/app.py`):
- External to Houdini, survives restarts
- Timeline cells, convergence line chart (`intent_match` + `behavioral_pass_rate`), iteration detail panel
- Run: `streamlit run app.py -- --run-id <run>`
- Best when: loop completes ≥3 iterations, studying convergence

**Approach B — In-Houdini Python Panel** (`loop_monitor/panel.py` + `graphpaint.py`):
- Docked beside the Network Editor
- `graphpaint.py` colours nodes blue (touched), red (cook error), green (ok)
- Registered via `loop_monitor_panel.pypanel` XML wrapper
- Best when: interactive Houdini sessions, graph-level debugging

Full spec: `project-docs/loop-monitor-ui-brief.md`

---

## 7. VEX Rules (baked into CLAUDE.md)

| Rule | Detail |
|---|---|
| Explicit type prefixes | `v@vel`, `i@id`, `f@mass`, `s@name` — never implicit float |
| Function declaration order | Declare BEFORE use — no recursion |
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

## 8. Key Design Decisions

**Why hrpyc proxy strings not objects:** `hrpyc` proxy objects don't support `__eq__`/`__hash__`. The Editor's action schema must use `node_path` strings throughout. The Editor payload must explicitly carry `node_path` per action.

**Why iterative not all-at-once:** IMPROVE (2025) confirms iterative component refinement (one targeted change → observe delta) outperforms all-at-once optimization as performance approaches ceiling.

**Why behavioral critic before VLM:** VLM critique is expensive and cannot see silent behavioral failures (wrong cook state, geometry statistics). Behavioral critic runs headless via `hython` with parametric sweeps — fast, typed, deterministic. VLM is gated after behavioral pass.

**Why Translator is separate from Editor:** Collapses of perception and action into one agent are the primary error source in comparable systems (dual-agent PCG 2024). Translator proposes one change; Editor executes it.

**VQAScore caution:** VQAScore (ECCV 2024) is the best automated alignment scalar but is trained on natural images — distribution shift on Houdini viewport renders needs validation before trusting it for convergence decisions.

---

## 9. Open Questions

1. **Bridge choice finalization:** fxhoudinimcp for MCP tool calls + hrpyc for direct orchestrator `hou` access — confirm this split works in practice before committing.
2. **VQAScore validation:** run on Houdini viewport renders to quantify distribution shift.
3. **Behavioral critic parametric sweep design:** which parameters to sweep per node type, what constitutes a "pass."
4. **Convergence judge conflict of interest:** separate judge avoids the critic marking its own work as done.
5. **`.hip` snapshot strategy:** when to snapshot, how many to keep, backtracking policy.

---

## 10. Research Sources

| Source | Key contribution |
|---|---|
| threedle/ll3m | Bridge pattern, event schema, headless render, error heuristics to improve |
| MoonLake AI blog | Behavioral critic / scenario tests concept validation |
| SideFX hrpyc docs | Bridge implementation, proxy limitations |
| oculairmedia/houdini-mcp | Reference bridge + 418-test suite |
| SceneX AAAI 2025 | PCGHub = Reference DB; discrete-op failure modes |
| GPTEval3D CVPR 2024 | VLM pairwise comparison, multi-view obs package |
| VQAScore ECCV 2024 | Automated alignment scalar for convergence judge |
| Dual-Agent PCG 2024 | Actor/Critic validation, docs-as-context generalisation |
| IMPROVE 2025 | Iterative component refinement > all-at-once |

Full annotations: `project-docs/fetched-sources.md`
