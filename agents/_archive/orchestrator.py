"""Orchestrator — drives the gated dual-critic loop.

Phases (per LL3M §4 mapping in INSTRUCTIONS.md and project brief §5):
  initial_creation  → translator+editor seed a starting graph
  auto_refinement   → loop: behavioral → vlm? → translator → editor → judge
  escalation        → on `stuck`, switch translator to structural mode

Run:  python agents/orchestrator.py --prompt "create a box" --mock
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.behavioral_critic import BehavioralCritic
from agents.convergence_judge import ConvergenceJudge
from agents.editor import Editor
from agents.emit import emit, events_path, new_run_id, run_dir
from agents.houdini_client import FxHoudiniMCPClient, make_client
from agents.translator import Translator
from agents.vlm_critic import VLMCritic

REPO_ROOT = Path(__file__).resolve().parent.parent


class Orchestrator:
    def __init__(self, run_id: str | None = None, *,
                 client_mode: str = "mock",
                 behavioral_mode: str | None = None,
                 max_iterations: int = 8,
                 validate_with_hython: bool = False,
                 hython_path: str | None = None,
                 target_node: str = "/obj/geo1/box1",
                 human_mode: bool = False):
        self.run_id = run_id or new_run_id()
        run_dir(self.run_id)
        self.client_mode = client_mode
        self.max_iterations = max_iterations
        self.validate_with_hython = validate_with_hython
        self.hython_path = hython_path
        self.human_mode = human_mode

        # default behavioral mode: live if we have a real bridge, mock otherwise
        if behavioral_mode is None:
            behavioral_mode = "live" if client_mode == "fx" else "mock"
        self.behavioral_mode = behavioral_mode

        self.target_node = target_node
        self.client = make_client(client_mode)
        self.translator = Translator(mode="parametric", human_mode=human_mode,
                                     client=self.client)
        self.editor = Editor(self.client)
        self.behavioral = BehavioralCritic(
            mode=behavioral_mode,
            client=self.client,
            fail_until_iteration=2,
        )
        self.vlm = VLMCritic(client=self.client, human_mode=human_mode)
        self.judge = ConvergenceJudge()

    def run(self, prompt: str) -> dict:
        self.prompt = prompt  # threaded to Translator and VLM in later steps
        # Fresh start: clear any prior events for this run-id so a re-run
        # under the same id doesn't append onto stale iterations.
        ep = events_path(self.run_id)
        if ep.exists():
            ep.unlink()

        emit(self.run_id, 0, "0.0", "orchestrator", "start", {
            "prompt": prompt,
            "client_mode": self.client_mode,
            "behavioral_mode": self.behavioral_mode,
            "validate_with_hython": self.validate_with_hython,
            "target_node": self.target_node,
        })

        self._initial_creation(prompt)
        result = self._auto_refinement()

        if self.validate_with_hython:
            self._post_validate(result["iteration"])

        emit(self.run_id, result["iteration"], "end", "orchestrator", "finish",
             {"decision": result["decision"], "iterations": result["iteration"]})
        return result

    # ---- phases ----------------------------------------------------------

    def _initial_creation(self, prompt: str):
        """Seed graph — derives node type from target_node path, skips LLM subprocess."""
        parent = self.target_node.rsplit("/", 1)[0] or "/obj"
        fallback_type = self.target_node.rsplit("/", 1)[1].rstrip("0123456789")
        seed_actions = [
            {"node": parent, "op": "create", "type": "geo"},
            {"node": self.target_node, "op": "create", "type": fallback_type},
            {"node": self.target_node, "parm": "sizex", "value": 1.0,
             "change": "init", "rationale": "seed from prompt"},
            {"node": self.target_node, "parm": "sizey", "value": 1.0,
             "change": "init", "rationale": "seed from prompt"},
            {"node": self.target_node, "parm": "sizez", "value": 1.0,
             "change": "init", "rationale": "seed from prompt"},
        ]
        print(f"[init] Creating {self.target_node} ({fallback_type}) in {parent}")
        emit(self.run_id, 0, "0.1", "translator", "result", {
            "source": ["fallback"],
            "mode": "structural",
            "actions": seed_actions,
            "fallback": True,
        })
        self.editor.execute(self.run_id, 0, "0.2", seed_actions)

    def _auto_refinement(self) -> dict:
        last_judge: dict = {}
        last_translator: dict = {}
        last_behavioral: dict = {}
        last_vlm: dict = {}

        for it in range(1, self.max_iterations + 1):
            print(f"\n--- iteration {it}/{self.max_iterations} ---")

            # behavioral first (gated)
            print(f"[{it}.1] behavioral ({self.behavioral_mode})...")
            last_behavioral = self.behavioral.evaluate(
                self.run_id, it, f"{it}.1", self.target_node
            )
            b_status = "PASS" if last_behavioral["passed"] else "FAIL"
            print(f"[{it}.1] behavioral: {b_status}")

            # vlm only if behavioral passed
            print(f"[{it}.2] vlm..." if last_behavioral["passed"] else f"[{it}.2] vlm: skipped")
            last_vlm = self.vlm.evaluate(
                self.run_id, it, f"{it}.2", last_behavioral["passed"],
                prompt=self.prompt, node_path=self.target_node,
            )

            # translator merges feedback
            print(f"[{it}.3] translator ({self.translator.mode})...")
            last_translator = self.translator.translate(
                self.run_id, it, f"{it}.3",
                behavioral=last_behavioral,
                perceptual=last_vlm if last_vlm and not last_vlm.get("skipped") else {},
                graph_json=self.client.node_graph_json(),
                prompt=self.prompt,
                target_node=self.target_node,
            )

            # editor enacts the actions
            print(f"[{it}.4] editor: {len(last_translator['actions'])} action(s)...")
            self.editor.execute(
                self.run_id, it, f"{it}.4", last_translator["actions"]
            )

            # judge inspects whether to continue
            last_judge = self.judge.decide(
                self.run_id, it, f"{it}.5",
                behavioral=last_behavioral,
                vlm=last_vlm if last_vlm and not last_vlm.get("skipped") else {},
            )
            print(f"[{it}.5] judge: {last_judge['decision']} — {last_judge['reason']}")

            if last_judge["decision"] == "done":
                return {"decision": "done", "iteration": it}

            if last_judge["decision"] == "stuck":
                self._escalate(it)

        return {"decision": "max_iterations", "iteration": self.max_iterations}

    def _escalate(self, iteration: int):
        prev = self.translator.mode
        self.translator.set_mode(
            "structural" if prev == "parametric" else "parametric"
        )
        emit(self.run_id, iteration, f"{iteration}.6", "orchestrator", "escalate",
             {"from_mode": prev, "to_mode": self.translator.mode,
              "reason": "convergence_judge: stuck"})

    # ---- post-validation ------------------------------------------------

    def _post_validate(self, converged_iteration: int) -> None:
        """Run the hython behavioral_critic_runner against a saved .hip.

        Emits one event with event_type=post_validation tagged to the
        converged iteration so it sits *with* that iteration rather than
        creating a phantom orphan one.
        """
        if not isinstance(self.client, FxHoudiniMCPClient):
            emit(self.run_id, converged_iteration, "post.0",
                 "orchestrator", "post_validation_skipped",
                 {"reason": "client is not fx"})
            return

        hip_path = REPO_ROOT / "runs" / self.run_id / "snapshots" / "final.hip"
        hip_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client._rpc("scene.save_scene",
                             {"file_path": str(hip_path).replace("\\", "/")})
        except Exception as e:
            emit(self.run_id, converged_iteration, "post.0",
                 "orchestrator", "post_validation_skipped",
                 {"reason": f"save_scene failed: {e}"})
            return

        hython = self.hython_path or shutil.which("hython") or _default_hython()
        if not hython or not Path(hython).exists():
            emit(self.run_id, converged_iteration, "post.0",
                 "orchestrator", "post_validation_skipped",
                 {"reason": f"hython not found (looked at {hython!r})"})
            return

        cmd = [
            hython,
            str(REPO_ROOT / "agents" / "behavioral_critic_runner.py"),
            "--hip-file", str(hip_path).replace("\\", "/"),
            "--node-path", self.target_node,
            "--run-id", self.run_id,
            "--iteration", str(converged_iteration),
            "--step-id", "post.1",
            "--event-type", "post_validation",
            "--parm-sweep", "sizex", "sizey", "sizez",
        ]
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True,
                           timeout=300)
        except Exception as e:
            emit(self.run_id, converged_iteration, "post.0",
                 "orchestrator", "post_validation_skipped",
                 {"reason": f"hython subprocess failed: {e}"})


def _default_hython() -> str | None:
    """Best-effort default for Windows installs of Houdini 19.5.716."""
    candidate = (r"C:\Program Files\Side Effects Software\Houdini 19.5.716"
                 r"\bin\hython.exe")
    return candidate if Path(candidate).exists() else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", required=True)
    p.add_argument("--client", choices=["mock", "fx"], default="mock",
                   help="mock = MockHoudiniClient; fx = fxhoudinimcp HTTP bridge")
    p.add_argument("--behavioral", choices=["mock", "live"], default=None,
                   help="Behavioral critic backend. Defaults to 'live' when "
                        "--client=fx, else 'mock'.")
    p.add_argument("--run-id", default=None)
    p.add_argument("--max-iterations", type=int, default=8)
    p.add_argument("--validate-with-hython", action="store_true",
                   help="After convergence, spawn the hython behavioral "
                        "runner against a saved .hip and emit one "
                        "event_type=post_validation event.")
    p.add_argument("--hython-path", default=None,
                   help="Override hython.exe path used by --validate-with-hython.")
    p.add_argument("--target-node", default="/obj/geo1/box1",
                   help="SOP node path the loop operates on.")
    p.add_argument("--mode", choices=["auto", "human"], default="auto",
                   help="'human' pauses at VLM + Translator for terminal input.")
    args = p.parse_args()

    orc = Orchestrator(
        run_id=args.run_id,
        client_mode=args.client,
        behavioral_mode=args.behavioral,
        max_iterations=args.max_iterations,
        validate_with_hython=args.validate_with_hython,
        hython_path=args.hython_path,
        target_node=args.target_node,
        human_mode=args.mode == "human",
    )
    result = orc.run(args.prompt)
    print(f"run_id={orc.run_id}  decision={result['decision']}  "
          f"iterations={result['iteration']}  "
          f"behavioral={orc.behavioral_mode}")


if __name__ == "__main__":
    main()
