# Houdini Agentic System — Project Brief

> Machine-readable project context. Captures the full design conversation:
> thesis, reasoning, architecture, open questions, and references.
> Intended as a Claude Project knowledge file. Structured for both human
> and LLM consumption.

---

## 1. Project Thesis

Build an agentic system that controls **Houdini** (SideFX) to produce
procedural 3D content from high-level natural-language instructions.

**The explicit research focus is the feedback loop**, not the generation.
The feedback loop — how a critic evaluates output and how that evaluation
is turned into corrective action — is treated as the primary bottleneck of
this class of technology. The project's contribution is expected to live in
the loop, not in the geometry generation.

---

## 2. Origin — Three SIGGRAPH 2025 Papers

The project grew out of reviewing three SIGGRAPH 2025 technical papers.
All three are **integration papers** (combining existing components into
production-oriented pipelines) rather than fundamental algorithmic work.
This itself was a noted signal: SIGGRAPH is shifting toward workflow
integration as the hard rendering/perception problems mature.

### 2.1 MatCLIP — Light- and Shape-Insensitive PBR Material Assignment
- Extends Alpha-CLIP. Two encoders: a Part Encoder (masked image region)
  and a Material Encoder (PBR material rendered across 42 shape/lighting
  combinations). Aligned via contrastive learning.
- At inference: a Stable Diffusion image (depth+edge conditioned) is the
  "target look"; MatCLIP retrieves the best PBR material per part from
  MatSynth.
- 76.69% top-1 accuracy; +15pts over PhotoShape / MatAtlas.
- **Relevance to this project:** the material database used as a retrieval
  target directly informs the *reference database* idea (Section 12).

### 2.2 BuildingBlock — Structured Building Generation
- Two-phase: a Transformer-based diffusion model generates a box layout;
  an LLM enriches it into a rule-based JSON layout; PCG assembles geometry.
- Key strength: editability via the structured JSON intermediate.
- Key weakness: tiny dataset (~1.2k buildings), asset-library ceiling.
- **Relevance:** demonstrates the "diffusion layout -> LLM enrichment ->
  PCG assembly" pattern and the value of an inspectable intermediate
  representation.

### 2.3 EditDuet — Multi-Agent Video Non-Linear Editing
- Two LLM agents: an **Editor** (searches clips, edits a timeline) and a
  **Critic** (reviews timeline vs request, gives feedback or renders).
- **Self-supervised ICL exploration**: agents generate their own
  in-context demonstrations via explore/label/score/self-reflect — avoids
  hand-crafted examples. Transferable idea.
- In-loop Critic is **text-only** (Llama-8B). A **VLM (GPT-4o)** is used
  only as the *final evaluation judge*, not in the loop — for context-cost
  reasons.
- VLM judge agreed with human majority vote 80.6% of the time (vs 78.7%
  human-human agreement).
- **Relevance:** the Editor/Critic skeleton is the architectural seed for
  this project. Also the explicit source of the "in-loop VLM critic is
  unsolved" insight.

---

## 3. Prior Art — Agentic Architecture for Software Control

Systems reviewed as references for controlling DCC / software via agents:

| System | Domain | Key idea relevant here |
|---|---|---|
| **SceneX** (Zhou et al. 2024) | Blender PCG | PCGBench (asset + API-doc repo) + PCGPlanner agent; emits **discrete API actions**. Executability/Success rates decline as task complexity grows — same scaling bottleneck. |
| **3D-GPT** (Sun et al. 2023) | Blender | Early instruction-driven procedural generation agent. |
| **SceneCraft** (Hu, Iscen et al.) | Blender | LLM agent synthesizes scenes as Blender code; scene graph as blueprint. |
| **LL3M** (threedle, 2025) | Blender | **Closest existing system to this project.** Multi-agent (plan/retrieve/write/debug/refine); writes Python code (not discrete actions); **visual critique agent** analyses renders vs prompt; **BlenderRAG** = RAG over API docs; shared code context across agents. Open source: github.com/threedle/ll3m |
| **MoonLake AI** | Blender (commercial) | World-modeling agent w/ computer-use inside Blender. **Independently identified the verification loop as the bottleneck.** Their answer: **scenario tests** — executable behavioural tests grounded in real issues/PRs that catch *silent behavioural failures* a VLM cannot see. Source of this project's behavioural-critic idea. |
| **BAGEL** (Murty et al. 2024) | Web nav | Single-agent self-supervised exploration / self-labeling (EditDuet extends this to multi-agent). |
| **VisProg** (Gupta & Kembhavi 2023) | Vision tasks | One-shot program generation; fails on iterative tasks — motivates iteration. |
| **ReAct** (Yao et al. 2022) | General | Foundational reason+act loop. |
| **Voyager** (Wang et al. 2023) | Minecraft | Skill-library accumulation over time — an angle none of the SIGGRAPH papers address. |
| **Reflexion / Self-Refine** | LLM (text) | Closest proven *in-loop* self-critique patterns; mostly text-domain. |

**Key gap identified:** no published system does agentic control of
Houdini's *procedural node-graph* paradigm specifically. Blender work
assumes destructive mesh editing or code generation. Houdini's node graph
+ VEX is genuinely different. This gap is the project's differentiation.

---

## 4. The Core Problem — Why the Feedback Loop Is the Bottleneck

For the editor to improve, critic feedback must be:
1. **Accurate** — correctly identifies what is wrong.
2. **Actionable** — maps to an operation the editor can actually perform.
3. **Specific** — "geometry looks wrong" is useless; "bevel radius on the
   top edge too large relative to face width" is useful.
4. **Grounded** — refers only to things that exist in the current state.

**Root cause of fragility:** the critic and editor do not share a
representation. The critic sees an image and produces natural language;
the editor consumes language and produces function calls. Translation is
lossy at every hop and errors compound across iterations.

EditDuet's self-supervised ICL exploration is a *patch* for a broken
feedback loop (it teaches agents to communicate by example), not a
structural fix.

---

## 5. System Architecture — Agents and Roles

Five components. The critic is split into two (Section 9).

### 5.1 Critic (VLM) — perceptual
- Sees the composed observation package (Section 7) + user prompt.
- Judges *visual/aesthetic* quality only — proportion, detail, intent
  match. Never mentions nodes or parameters.
- Output is **structured**, not prose:
  ```json
  { "intent_match": 0.4,
    "issues": [
      {"type": "proportion", "description": "...", "priority": "high"}
    ] }
  ```

### 5.2 Translator — maps visual feedback to Houdini actions
- The agent the other papers omit (they collapse it into the critic,
  which is *why their loops are fragile*).
- Takes structured critic issues + current node-graph JSON, outputs a
  concrete Houdini action list with rationale.
- Separating it keeps the critic grounded in perception, isolates
  translation errors, and makes the component independently testable.
- **Two modes:** *parametric* (tweak existing node parameters) and
  *structural* (rebuild a subgraph). Switches mode when the loop stalls.

### 5.3 Editor — pure executor
- Takes the action list, calls the Houdini Python API (`hou`).
- No reasoning, no interpretation. Reports execution results/errors back
  to the **Translator** (not the critic).
- Logs each attempt: call, result, before/after values.

### 5.4 Convergence Judge
- Runs after each full iteration. Lightweight, text-only.
- Inputs: history of critic scores, iteration diff, iteration count.
- Decides: **continue** / **stuck** / **done**.
- Fixes EditDuet's conflict of interest (there the feedback-giving critic
  also decides when to render).

### 5.5 Escalation path (when "stuck")
- Ask the user for clarification, OR
- Backtrack to a previous graph state and try another approach, OR
- Switch the Translator from parametric to structural mode.

---

## 6. The VLM Critic — Observation Package

A raw viewport screenshot is a poor VLM input. An artist sees geometry in
the context of intent; the VLM sees flat pixels. The critic input must be
a **composed observation package**, assembled programmatically:

**Geometry representation**
- Shaded viewport at a meaningful angle.
- Wireframe overlay (topology, edge loops, polygon density).
- Multiple simultaneous views (front/side/top/perspective).
- Close-up crop of the detail region for procedural patterns.

**Material/shading context**
- Matcap or simple PBR shading (proportion reads better than flat grey).
- Normal-visualization pass (catches shading artifacts).
- Optional AO pass (cavity/contact issues).

**Annotation layer** (drawn on the image before the VLM sees it — this
automates what a TD does manually when marking up a review)
- Bounding box with labeled dimensions.
- Arrows pointing to nodes changed in the last iteration.
- Highlighted regions where cook errors occurred.
- Wireframe colored by polycount density.

**Temporal context**
- Pass iterations N-2, N-1, current together, labeled with what changed —
  lets the critic detect oscillation, not just current-state correctness.

**Geometry statistics as text** (processed alongside the image)
- Point/primitive counts, bbox dimensions, delta from last iteration,
  cook time, error list.

> Houdini advantage over EditDuet's video domain: the observation space is
> fully under programmatic control — selective render passes, any geometry
> property, isolated node contributions, with/without comparison renders.

The assembly step is effectively its own subsystem.

---

## 7. The Behavioral Critic — Test Harness

Deterministic, **no LLM**. Catches **silent behavioural failures** a VLM
cannot see — a setup that looks correct at the default slider value but
breaks across its parameter range. For procedural work this is arguably
the more important failure class, since the whole point of procedural is
that it must hold across a range, not one frozen state.

Adapted from MoonLake's "scenario test" concept. The Houdini analog of a
scenario test is a **parametric stress test**.

**Tests performed:**
- *Structural invariants* on current state: manifold, no degenerate
  primitives, no NaN point positions, non-empty geometry.
- *Parametric sweeps*: for each exposed (user-facing) parameter, sample N
  values across its range, cook, check validity.
- *Frame sweeps* (if time-dependent): cook at start/mid/end frames.
- *Downstream survival*: feed output into a standard test operation,
  confirm it does not error.

**Pseudocode:**
```python
def behavioral_critic(node, exposed_parms):
    report = {"passed": True, "failures": []}

    # 1. Structural invariants on current state
    geo = node.geometry()
    for check in (check_manifold, check_degenerate_prims,
                  check_nan_positions, check_nonzero_geo):
        if not check(geo):
            report["failures"].append(("structural", check.__name__))
            report["passed"] = False

    # 2. Parametric stress test
    for parm in exposed_parms:
        original = parm.eval()
        lo, hi = parm_range(parm)
        for v in sample_range(lo, hi, n=5):
            parm.set(v)
            try:
                node.cook(force=True)
                g = node.geometry()
                if g.intrinsicValue("primitivecount") == 0:
                    report["failures"].append(
                        ("parametric", parm.name(), v, "empty output"))
                    report["passed"] = False
            except hou.OperationFailed as e:
                report["failures"].append(
                    ("parametric", parm.name(), v, str(e)))
                report["passed"] = False
        parm.set(original)  # always restore

    # 3. Frame sweep if time-dependent
    if node.isTimeDependent():
        for frame in (start, mid, end):
            ...  # cook + invariant check

    return report
```

**Open design point:** how exposed parameters are identified. Preferred
convention — the agent always promotes user-facing controls to a
top-level subnet/null, and the behavioural critic stress-tests only those.
Side benefit: this forces the agent to build *properly parameterized*
procedural setups, which is the desired Houdini output anyway.

---

## 8. The Dual-Critic Gated Loop

The two critics run **gated in sequence**, not in parallel:

```
Editor produces state
        |
        v
[ Behavioral Critic ]   deterministic, cheap -- run FIRST
        |
    +---+---+
   FAIL    PASS
    |        |
    |        v
    |   [ VLM Critic ]   expensive -- only if structurally sound
    |        |
    v        v
[ Translator ]   merges whichever feedback arrived
        |
        v
   Editor  -->  Convergence Judge   (needs BOTH signals green)
```

**Rationale for gating:** if geometry is non-manifold / producing NaNs,
there is no point spending a VLM call on aesthetics. Fix structure first.
Most early iterations fail structurally and never invoke the VLM — keeps
cost low.

**Translator merges typed feedback:**
```json
{
  "behavioral": [
    {"parm": "wall_height", "value": 4.2, "error": "empty output"}
  ],
  "perceptual": [
    {"type": "proportion", "issue": "bevels too uniform", "priority": "med"}
  ]
}
```
Behavioral failures get priority (concrete, unambiguous, translate almost
mechanically). Hard translation effort is reserved for fuzzy perceptual
feedback.

**Convergence requires both signals:**
```
DONE  <=>  behavioral.passed == True
      AND  vlm.intent_match >= threshold
      AND  delta(last two iterations) < epsilon
```
One objective signal (tests pass) + one subjective signal (looks right).
Ship only when both agree. No conflict of interest.

---

## 9. The Reference Database

Converts the VLM critic from a zero-shot absolute judge (its weakest mode)
into a grounded comparator (its strongest mode).

**Contents:**
- *Target exemplars* — reference images of the intended thing (mirrors
  MatCLIP's material database usage).
- *Quality anchors* — paired good/bad examples of known failure modes
  (non-manifold, false uniformity, z-fighting, UV distortion) so the
  critic can *name* failures precisely.
- *Canonical solutions* — known-good node-graph + output for common tasks;
  feeds the Translator too, not just the critic.

**Retrieval, not context-stuffing:** embed prompt + geometry caption,
retrieve top-k references (same CLIP-retrieval pattern as MatCLIP and the
EditDuet search engine).

**Two comparison modes:**
- *Visual* — current viewport vs reference image, VLM perceptual diff.
- *Structural* — diff agent graph vs canonical graph directly, **no VLM**,
  deterministic, cheaper. Underrated.

**Flywheel:** every bad output the agent produces becomes a labeled
quality anchor — the system self-generates critic training data, like
EditDuet's exploration but persistent across sessions.

**Caution:** a reference DB biases toward conventional solutions. For
genuinely novel procedural setups the Convergence Judge / Translator must
be able to discount reference-based feedback when the user wants something
unusual.

---

## 10. Proven Techniques for VLM Critics

Ordered by robustness:

1. **Pairwise comparison over absolute scoring** — most robust finding in
   the VLM-as-judge literature. EditDuet's judge always compares two
   timelines. For this loop: ask "is current iteration closer to
   reference / better than previous?" not "is this good?" — also yields
   convergence signal for free.
2. **Rubric / criteria decomposition** — score named criteria separately
   (proportion, detail, topology, intent match), not one holistic score.
   More reliable, more debuggable (Lee et al. 2024).
3. **Chain-of-thought before verdict** — force the VLM to describe what it
   sees before judging.
4. **Trained reward models as alternatives** — ImageReward, PickScore,
   HPSv2, VQAScore. VQAScore (yes/no VLM questions for alignment) is most
   interesting, but all are trained on natural/T2I images — need
   validation/fine-tuning on 3D viewport renders.

**Critical distinction:** EditDuet's in-loop critic is text-only; its VLM
is only the *final judge*. This project wants a VLM **in the loop** —
which is closer to research frontier than settled practice. The proven
foundation is pairwise + rubric + reference grounding; the in-loop part is
the genuine contribution.

---

## 11. Houdini Integration

**Action space (via `hou` Python API):**
```python
hou.node('/obj').createNode('geo')   # create node
node.parm('tx').set(1.0)             # set parameter
node.setInput(0, other_node)         # connect
node.cook()                          # evaluate
hou.hipFile.save('out.hip')          # persist
```
Editor functions: `create_node`, `set_parm`, `connect_nodes`, `run_vex`,
`delete_node`, `query_node_state`.

**Observation space:**
- Node-graph structure serialized as JSON.
- Parameter values of selected nodes.
- Cook errors / warnings.
- Geometry statistics (point/prim counts, bbox, attribute list).
- Viewport renders for the VLM critic.

**Central design fork — action representation:**
- *Discrete node-graph operations* (SceneX-style): structured,
  inspectable, limited expressiveness.
- *Write VEX / Python code* (LL3M-style): far more expressive, plays to
  Houdini's strengths, harder to validate/debug.
- **Leaning:** the code-generation route fits a VEX-heavy workflow; LL3M
  proves the multi-agent + visual-critique + RAG loop works in that mode.

---

## 12. Deployment & Tooling

**Replit assessment:** *not suitable for the core.* Houdini cannot run in
a Replit cloud container — `hou` is not pip-installable, ships inside a
licensed Houdini install, GUI/GPU heavyweight. Replit *can* help with the
orchestration layer (LLM calls, the multi-agent loop) prototyped against
*mocked* Houdini responses, the RAG component, and the dashboard. But the
tight "edit agent code -> watch real Houdini" cycle pushes toward **local
development**.

**Required architecture (regardless of dev environment):**
```
Agent orchestrator  <--socket/RPC-->  Houdini bridge
(LLM calls, the loop)                 (runs inside Houdini/hython,
                                       executes `hou`, returns state)
```
Same pattern as Blender MCP — an addon opens a socket; the agent talks to
it. The bridge is small; the orchestrator is the bulk of the code and is
environment-agnostic.

---

## 13. Monitoring Interface — Dashboard

A monitoring UI is a hard requirement, not a nice-to-have: a feedback-loop
system must be observable to be debuggable. The UI is a separate layer
from where code runs and can be local regardless.

**Build path:** Streamlit first (timeline + chart + tabs in ~1 day),
graduate to React + FastAPI when real-time streaming and a draggable
timeline scrubber are wanted.

**Layout:**
```
+----------------------------------------------------+
|  Run: brick-wall-03      Status: running   it.4    |
+----------------------------------------------------+
|  TIMELINE   [1][2][3][4]...   <- click a cell      |
|             green=converged amber=vlm red=behav    |
+----------------------------------------------------+
|  CONVERGENCE CHART                                 |
|   two lines: intent_match  &  behavioral_pass_rate |
|   plotted across iterations                        |
+----------------------------------------------------+
|  ITERATION DETAIL                                  |
|  [composed     | [Behavioral]  | node graph diff ] |
|   viewport     | [VLM critique]|                  |
|   render       | [Translator]  |                  |
|   (annotated)  | [Editor log]  |                  |
+----------------------------------------------------+
|  Step | Pause | Play | [ ] edit feedback           |
+----------------------------------------------------+
```

**Two highest-value elements for the research goal:**
- *Convergence chart* — makes oscillation / stalling visible as it
  happens.
- *Node-graph diff* — shows what actually changed vs what the Translator
  asked for; the gap between those two is where most bugs live.

**Stepping control** — with "edit feedback" on, the loop pauses after the
critic, shows the structured feedback, and lets the user edit it before it
reaches the Translator. Turns the dashboard from a passive monitor into an
instrument for probing exactly where the loop breaks. EditDuet and LL3M
relegate the human to watching; for a project studying the loop, mid-loop
intervention is how its failure points are learned.

---

## 14. Event Schema

One envelope, emitted by every agent. Fixed envelope + flexible payload.
Heavy artifacts (renders, snapshots) are written to disk; payload carries
a `*_ref` path. Keeps the log tailable.

**Envelope:**
```json
{
  "run_id":      "uuid",
  "iteration":   4,
  "step_id":     "4.2",
  "agent":       "behavioral_critic",
  "event_type":  "result",
  "timestamp":   "2026-05-16T...",
  "duration_ms": 340,
  "payload":     { }
}
```

**Per-agent payloads:**
```json
// Editor
{ "actions": [
    {"call": "box1.parm('sizey').set(1.3)",
     "result": "ok", "before": 1.0, "after": 1.3}],
  "cook_errors": [],
  "graph_ref": "snapshots/4_2.json" }

// Behavioral Critic
{ "passed": false,
  "structural": [{"check": "manifold", "passed": true}],
  "parametric": [
    {"parm": "wall_height", "value": 4.2,
     "passed": false, "error": "empty output"}] }

// VLM Critic
{ "intent_match": 0.62,
  "issues": [{"type": "proportion",
              "description": "bevels too uniform",
              "priority": "high"}],
  "observation_ref": "renders/4_3_composed.png" }

// Translator
{ "source": ["behavioral", "perceptual"],
  "mode": "parametric",
  "actions": [{"node": "box1", "parm": "sizey",
               "change": "increase ~30%",
               "rationale": "fix proportion"}] }

// Convergence Judge
{ "decision": "continue",
  "intent_match": 0.62,
  "behavioral_pass_rate": 0.8,
  "delta": 0.15,
  "reason": "improving, below threshold" }
```

**Plumbing:** every agent calls one helper — `emit(event)` — appending a
JSON line to `runs/<run_id>/events.jsonl`. The dashboard tails that file.
Agents and UI never import each other.

---

## 15. Reasoning Log — Key Judgment Calls

Design decisions and *why*, preserved so rationale is not lost:

- **Split the critic into perceptual + behavioral.** A VLM cannot see
  silent behavioural failures (works at default, breaks across range).
  For procedural content, robustness across the parameter space is the
  point. Two critics catch different, complementary failure classes.
- **Gate the critics (behavioral first).** Structural validity is a
  precondition for aesthetic evaluation. Gating also makes most early
  iterations cheap (no VLM call).
- **Introduce a dedicated Translator.** EditDuet/SceneX/LL3M fold
  translation into the critic; this is the source of their loop
  fragility. Separating perception (critic) from translation (Translator)
  isolates error and enables independent testing.
- **Structured critic output, not prose.** Forces grounding; makes
  Translator interpretation deterministic. Cost: reduced expressiveness —
  accepted.
- **Convergence Judge separate from the critic.** EditDuet lets the
  feedback-giving critic also decide when to render — a conflict of
  interest. A separate judge with an external delta signal is more
  reliable.
- **Pairwise over absolute scoring.** Most robust VLM-as-judge finding;
  also yields convergence signal.
- **Reference database as a comparator.** Moves the VLM from absolute
  judgment (weak) to comparison (strong). Caution noted re: bias toward
  conventional solutions.
- **Local development, not Replit.** Houdini cannot run in a cloud
  container; the dev cycle needs real Houdini in the loop.
- **Monitoring UI as a first-class instrument with stepping.** The
  project studies the loop; the loop must be observable and interruptible.
- **Action-representation fork (discrete ops vs code-gen) left open**,
  leaning code-gen for a VEX-heavy workflow per LL3M precedent.

---

## 16. Open Questions / Decisions Pending

- Action representation: discrete node-graph ops vs VEX/Python code-gen.
- How exposed parameters are identified for the behavioral critic
  (proposed: top-level subnet/null promotion convention).
- VLM model choice for the in-loop critic (frontier-dependent).
- Whether trained reward models (VQAScore etc.) can be adapted to 3D
  viewport renders or must be replaced by a general VLM.
- Translator parametric-vs-structural mode-switch trigger logic.
- Reference-database construction strategy and how to keep it from
  over-biasing toward conventional output.

---

## 17. Suggested Next Steps

1. Build the `emit()` helper + a Streamlit skeleton that reads
   `events.jsonl` — gives a working dashboard against **mock** events
   before any Houdini is wired in.
2. Prototype the multi-agent loop with mocked Houdini responses (validates
   Critic -> Translator -> Editor -> Convergence handoffs).
3. Build the Houdini bridge (socket service inside Houdini/hython).
4. Implement the Behavioral Critic against real cooks (deterministic, no
   model — easiest real component to validate).
5. Implement the VLM Critic observation-package assembly.
6. Wire the full gated dual-critic loop.
7. Read the LL3M paper/code in full before finalizing the Translator —
   it solves an adjacent version of the same problem.

---

## 18. References & Influences

**SIGGRAPH 2025 papers (origin):**
- MatCLIP — Light- and Shape-Insensitive Assignment of PBR Material
  Models. https://birsakm.github.io/matclip/
- BuildingBlock — A Hybrid Approach for Structured Building Generation.
- EditDuet — A Multi-Agent System for Video Non-Linear Editing.

**Agentic / DCC-control systems:**
- SceneX (Zhou et al. 2024) — PCGBench, PCGPlanner.
- 3D-GPT (Sun et al. 2023).
- SceneCraft (Hu, Iscen et al.).
- LL3M — Large Language 3D Modelers (threedle, 2025).
  github.com/threedle/ll3m
- MoonLake AI — world-modeling agent. moonlakeai.com/blog/3d-agent
- BAGEL (Murty et al. 2024).
- VisProg (Gupta & Kembhavi 2023).
- ReAct (Yao et al. 2022).
- Voyager (Wang et al. 2023).
- Reflexion / Self-Refine (Madaan et al. 2024).

**Evaluation / VLM-as-judge:**
- LLM-as-a-judge — Zheng et al. (MT-Bench).
- Lee et al. 2024 — rubric-following VLM evaluation.
- Kim et al. 2024b — VLM evaluation.
- Reward models — ImageReward, PickScore, HPSv2, VQAScore.

**Foundational components referenced:**
- Alpha-CLIP, CLIP (Radford et al. 2021).
- MatSynth, 3DCoMPaT++ (datasets).
- DiffuScene, ATISS, Transcript2Video (baselines in the source papers).

**Research keyword clusters (for further reading):**
VLM-as-judge / pairwise preference judgment; Self-Refine / Reflexion /
iterative refinement LLM; multi-agent LLM collaboration; ReAct / function
calling / agentic workflow; GUI agents / computer-use agents / OSWorld;
in-context demonstration generation / self-supervised exploration;
retrieval-augmented generation / CLIP retrieval / reference-guided
evaluation; agent convergence detection / stopping criteria; Houdini
`hou` module / text-to-procedural-modeling / node-graph generation.
