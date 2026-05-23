# Houdini Agentic System — Fetched Source Notes

> Compiled from live fetches. Supplements the project brief.
> Each entry: what was confirmed, what's new, direct relevance to the project.

---

## 1. LL3M (threedle) — Primary Blender Reference
**Repo:** github.com/threedle/ll3m  ·  **Stars:** 523  ·  **License:** Academic/Evaluation

### Confirmed architecture
- `addon.py` inside Blender opens HTTP on **port 8888**; `main.py` is the
  orchestrator (client side, 1172 lines).
- Loop phases: `initial_creation` → `auto_refinement` → `user_guided_refinement`.
- Server-side (LLM calls, multi-agent reasoning) is **defunct** — the
  original Claude Sonnet 3.7 endpoint was retired. Only the client
  pattern is usable.
- Client polls `/runs/{session_id}/events` (JSONL event stream). Each
  event type: `INSTRUCTION_EXECUTE_BLENDER`, `INSTRUCTION_REQUEST_USER_INPUT`,
  `RUN_COMPLETED`, `RUN_FAILED`, `PHASE_HEARTBEAT`.
- **Error heuristic** (not an LLM): string match on `"error:"`, `"traceback"`,
  `"failed"`, `"context is incorrect"` in execution result — this is the
  "behavioural critic" analogue, and it's weak. This is the gap we fill.
- Headless mode: saves `.blend` snapshot, runs `hython`-style headless
  render, uploads PNGs. Translatable to Houdini's `hython` + `hou.hipFile`.
- Session refinement: `--session-id + --prompt` loads `draft.py` from a
  prior session, re-runs. Analogous to our graph-state backtracking.

### Key delta from our architecture
| LL3M | Our project |
|------|-------------|
| Server handles all LLM calls (opaque) | Orchestrator is local, transparent |
| No Translator agent | Dedicated Translator separates perception from action |
| String heuristic error detection | Typed Behavioral Critic (parametric sweeps) |
| No structured critic output | Structured JSON critique enforced |
| VLM critique is in the loop | Same, but gated after behavioral pass |
| No convergence judge | Separate Convergence Judge (avoids conflict of interest) |

### Portability notes for Houdini bridge
- `addon.py` pattern → port to `hwebserver` or `hrpyc` inside Houdini.
- `BlenderClient.execute_code()` → becomes `hou` calls over `hrpyc`
  or a thin HTTP wrapper using `hwebserver`.
- `render_scene()` output path rewriting → becomes `hou.hipFile.save()`
  + opengl/mantra/karma ROP batch cook.

---

## 2. MoonLake AI — Scenario Tests / Behavioral Critic Origin
**URL:** moonlakeai.com/blog/3d-agent  ·  **Raised:** $28M seed (Threshold, NVIDIA Ventures, AIX Ventures)

### Confirmed from search
- Computer-use agent operating directly inside **Blender**. Not Houdini — confirms our gap.
- The verification problem is explicitly named: *"the verification process
  requires causal, geometric, and spatial understanding of the world, priors
  that are never stated in the task or instruction."*
- Their answer: **scenario tests** — small, controlled interaction setups
  that place the world in a particular state, perform an action, and check
  resulting player-visible behavior.
- Grounded in **real issues and pull requests** — preserves goal-oriented
  language including both feature construction and debugging.
- Key quote (paraphrased): scenario tests make *silent behavioral failures*
  visible by probing whether worlds respond correctly under specific conditions.
- Optimization guided by **layered objectives** assessing scene quality at
  multiple levels — multi-level critique is exactly our dual-critic design.

### Relevance
- Validates the behavioral critic concept directly; MoonLake independently
  reached the same conclusion about the bottleneck.
- Their scenario tests are game-state-based; ours are parametric sweeps
  on Houdini procedural parameters — same class of test, different domain.

---

## 3. Houdini Bridge — `hrpyc` / `hwebserver`
**Official docs:** sidefx.com/docs/houdini/hom/rpc.html

### Key facts confirmed
- `hrpyc` is a thin wrapper around **RPyC**. Default port **18811**.
- Start from inside Houdini's Python shell:
  ```python
  import hrpyc
  hrpyc.start_server()          # threaded, port 18811
  # or
  hrpyc.start_server(use_thread=False)  # blocks main thread
  ```
- Remote client (orchestrator side):
  ```python
  import hrpyc
  connection, hou = hrpyc.connect("localhost")
  node = hou.node("/obj/sphere1")
  node.parm("scale").set(2.0)
  ```
- **Limitation:** rpyc proxy objects don't support Python operators
  (`__eq__` etc.). Can't compare `hou.OpNode` proxies directly.
- `hwebserver` (fxhoudinimcp uses this) is HTTP-based — simpler for JSON
  payloads, less transparent for complex `hou` object graphs.

### Bridge architecture decision
- **hrpyc**: best for transparent `hou` access, lower overhead, already
  used by `oculairmedia/houdini-mcp` (43 tools, 418 tests).
- **hwebserver**: better for JSON/REST, already used by fxhoudinimcp
  (168 tools, 19 categories) — which we have installed.
- **Recommendation:** use the installed `fxhoudinimcp` (hwebserver/port 8100)
  as the bridge for day-to-day MCP work; add `hrpyc` as a secondary path
  for the agent orchestrator where direct `hou` object access is needed.

### `hython` for headless
- `hython` = Houdini's Python interpreter without GUI.
- Runs `hou` scripts without a display — ideal for behavioral critic
  parametric sweeps (cook and check, no render needed).
- Invocation: `hython path/to/script.py [args]`
- Memory/speed advantage: no graphical components loaded.

---

## 4. SceneX — PCGBench / PCGPlanner (AAAI 2025)
**Paper:** arxiv.org/abs/2403.15698

### Confirmed
- Two components: **PCGHub** (procedural asset library + hand-crafted API docs)
  and **PCGPlanner** (LLM agent generating executable Blender API actions).
- Three-stage planner: task planning → asset retrieval → action execution.
- Discrete API actions (not code-gen). City spanning 2.5km×2.5km; reduces
  weeks of PCG work to hours for non-expert users.
- **Failure mode** (confirmed in brief): executability/success declines with
  task complexity — exactly what the behavioral critic stress-tests are
  designed to catch early.

### Our delta
- We lean code-gen (VEX/Python) over discrete ops — more expressive for
  Houdini's node-graph paradigm. SceneX's discrete-op approach is the
  alternative we consciously rejected.
- Their PCGHub = our Reference Database (canonical solutions + API docs).
  BlenderRAG (LL3M) = same concept for RAG over API docs.

---

## 5. GPT-4V as Human-Aligned Evaluator for Text-to-3D (CVPR 2024)
**Paper:** arxiv.org/abs/2401.04092  ·  **Code:** github.com/3DTopia/GPTEval3D

### Key findings
- GPT-4V used to **compare two 3D assets pairwise** according to
  user-defined criteria → Elo ratings. Strongly aligns with human judgment.
- Pairwise > absolute scoring — same finding the brief cites from EditDuet.
- **120 evenly spaced view renders** per asset fed to the VLM — confirms
  multi-view observation package is important even for 3D eval.
- Criteria are user-defined (rubric decomposition) — supports the brief's
  structured critique JSON approach.
- **Direct relevance:** this is essentially the VLM critic we need for
  text-to-procedural evaluation, adapted to viewport renders instead of
  T2I renders.

### Adaptation notes for our project
- Their 120-view rendering is expensive; our annotated 4-view package
  (front/side/top/persp + wireframe overlay) is the practical equivalent.
- Their Elo system → we use `intent_match` scalar + pairwise delta for
  convergence signalling.
- Their code (github.com/3DTopia/GPTEval3D) is directly portable for the
  VLM critic comparison logic.

---

## 6. VQAScore — Text-to-Visual Alignment Metric (ECCV 2024)
**Paper:** arxiv.org/abs/2404.01291  ·  **Model:** CLIP-FlanT5

### Key findings
- Computes `P("Yes" | "Does this figure show {text}?")` using a VQA model.
- Outperforms CLIPScore, ImageReward, PickScore, and GPT-4V baselines on
  8 image-text alignment benchmarks.
- Trained on images only; **generalizes to video and 3D models** — this
  is the key fact. Preliminary success on 3D evaluation confirmed.
- CLIP acts as "bag of words" — conflates relation order ("horse eats grass"
  vs "grass eats horse"). VQAScore fixes this with bidirectional encoder.
- Used by Google DeepMind to evaluate Imagen3.

### Relevance and caution
- Best candidate for an automated alignment signal in the convergence judge
  (cheaper than a VLM call, deterministic).
- **Caution from brief:** trained on natural/T2I images; 3D viewport renders
  are a distribution shift. Need validation runs before trusting the score.
- Practical path: use VQAScore for rough alignment trending across iterations,
  use GPT-4V pairwise comparison for final convergence decisions.

---

## 7. Dual-Agent PCG for 3D Maps (Zero-shot, 2024)
**Paper:** arxiv.org/pdf/2512.10501

### Key finding
- Actor + Critic agent pair for PCG parameter configuration from NL prompts.
- "Dialogic process" — agents iteratively refine config, resolve ambiguities
  and correct errors autonomously. No gradient updates, pure in-context
  reasoning.
- No task-specific fine-tuning: general-purpose LLMs repurposed as domain-
  agnostic controllers by swapping reference documentation.
- **Outperforms single-agent baselines** on map generation — validates the
  multi-agent architecture over a simple prompt-then-execute approach.

### Relevance
- Validates the Critic/Translator separation (they have one "Critic" agent
  that does both — collapsing translation into perception as we avoid).
- Their "swapping reference documentation" = our BlenderRAG / HoudiniRAG.
- Direct evidence that documentation-as-context generalizes across PCG tools.

---

## 8. IMPROVE — Iterative Pipeline Refinement via LLM Agents (2025)
**Paper:** arxiv.org/abs/2502.18530

### Key finding
- "All-at-once" optimization (optimize entire pipeline before evaluating)
  fails as performance approaches maximum — makes further progress hard.
- **Iterative Refinement** (refine components in isolation, one at a time)
  produces more consistent gains.
- Directly supports our Translator → Editor split: the Translator proposes
  one targeted change; the Editor executes it; the loop observes the delta.
  This is iterative component refinement, not all-at-once.

---

## 9. hrpyc Module Reference (ikrima mirror)
**URL:** ikrima.github.io/houdini_additional_python_docs/hrpyc.html

### Summary
- `hrpyc` provides access to `hou` from a separate Python process via RPyC.
- Proxy objects: all method calls cross the network; results are local copies.
- **Key limitation:** proxied objects don't support `__eq__`, `__hash__` etc.
  Use `.path()` or `.name()` for identity comparisons.
- The agent orchestrator should work with path strings, not node object
  references, to avoid proxy comparison bugs.

---

## 10. oculairmedia/houdini-mcp — hrpyc Bridge
**Repo:** github.com/oculairmedia/houdini-mcp  ·  **Stars:** 18  ·  **Tests:** 418

### Architecture
- Two modes: **stdio** (hython directly, `start_server(use_thread=False)`)
  or **Docker HTTP** (remote, connects via `hrpyc`).
- `.mcp.json` for stdio mode:
  ```json
  { "mcpServers": { "houdini": {
      "command": "hython",
      "args": ["-c", "from houdini_mcp_plugin import start_server; start_server(use_thread=False)"]
  }}}
  ```
- Docker mode for when Houdini runs on a different machine — maps to our
  "agent orchestrator on one machine, Houdini on workstation" topology.

### Relevance
- 418 tests — largest test suite of the three MCP repos. Good reference for
  what to test in the behavioral critic and bridge validation.
- `hrpyc` mode is directly compatible with the headless orchestrator pattern
  (orchestrator doesn't need a Houdini install, just the rpyc library).

---

## Summary Matrix — What Each Source Contributes

| Source | Contributes to |
|--------|---------------|
| LL3M source code | Bridge pattern, event schema, headless render flow, error heuristics to improve |
| MoonLake blog | Behavioral critic concept validation, layered objectives |
| SideFX hrpyc docs | Bridge implementation details, proxy limitations |
| oculairmedia/houdini-mcp | Bridge reference implementation, test suite |
| SceneX AAAI 2025 | PCGHub = our Reference DB; discrete-op failure modes |
| GPTEval3D CVPR 2024 | VLM critic pairwise comparison, multi-view obs package |
| VQAScore ECCV 2024 | Automated alignment scalar for convergence judge |
| Dual-Agent PCG 2024 | Actor/Critic validation, docs-as-context generalization |
| IMPROVE 2025 | Iterative component refinement > all-at-once optimization |

---

## Open Questions Sharpened by Fetch

1. **Bridge choice:** `fxhoudinimcp` (hwebserver, installed) vs `hrpyc` 
   (lower-level, better for agent orchestrator). Likely: keep fxhoudinimcp
   for MCP tool access; add `hrpyc` for the agent's direct `hou` calls.

2. **VQAScore validation:** must run on Houdini viewport renders to confirm
   the distribution shift doesn't break alignment scoring before relying on it.

3. **hrpyc proxy limitation:** orchestrator must use path strings for node
   identity, not object references. Design the Editor's action schema around
   string paths from the start.

4. **LL3M headless pattern:** the `.blend` snapshot → headless render cycle
   maps to `.hip` snapshot → `hython` batch cook for behavioral critic sweeps.
   Consider making the behavioral critic run fully headless via `hython` 
   (no GUI Houdini process required for parametric sweeps).
