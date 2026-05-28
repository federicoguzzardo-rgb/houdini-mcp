# Archived — Autonomous Orchestrator

These files implement the autonomous dual-critic gated loop (orchestrator →
behavioral_critic → vlm_critic → translator → editor → convergence_judge).
They are parked here, not deleted.

## Why archived
The orchestrator model requires an Anthropic API key and burns per-token
credits on every iteration. The daily tool is now the interactive collaborator
(Claude Desktop, flat Pro rate) — see the project CLAUDE.md.

## When these become relevant again
- You have a concrete need for **unattended operation** (runs while you're away).
- You have API budget (pay-as-you-go or Max plan's programmatic pool), OR
- You run a local model (Ollama) capable enough for reliable Houdini work.

Until then, keep them parked. The interactive tool is faster for daily use.
