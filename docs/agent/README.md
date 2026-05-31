# Agent Docs Knowledge Base

This directory is the repo-local agent system of record for FPVS Toolbox. Agents should
start with `AGENTS.md`, `ARCHITECTURE.md`, and `docs/agent/agent-index.md`, then use
this map to choose the narrowest deeper source of truth.

User-facing MkDocs pages live under `docs/user/`.

Activate `.\.venv1` before running Python-based repo commands from agent docs.
Command examples that use `python` assume that environment is active.

## Directory Map

- `architecture/`: durable architecture maps, ownership boundaries, and behavior contracts.
- `design-docs/`: product and engineering beliefs that guide future design choices.
- `exec-plans/`: active plans, future plans, and technical-debt tracking.
- `generated/`: generated reference artifacts. Do not edit generated files by hand.
- `guides/`: developer setup and maintenance guidance.
- `product-specs/`: durable product behavior and workflow specifications.
- `quality/`: test-selection and verification-gate guidance.
- `references/`: external or copied reference material useful to agents.
- `reviews/`: pre-ship and review checklists.

## Entry Files

- `README.md`: this directory map.
- `agent-index.md`: fast command, skill, doc, and focused-test index.

## Moved Knowledge Files

- `design-docs/DESIGN.md`: design-system and UX guidance.
- `design-docs/FRONTEND.md`: PySide6 frontend implementation guidance.
- `design-docs/PRODUCT_SENSE.md`: product goals and user workflow priorities.
- `exec-plans/README.md`: plan index and planning rules.
- `guides/development.md`: developer setup and verification notes.
- `quality/QUALITY_SCORE.md`: current quality posture and gaps.
- `quality/RELIABILITY.md`: reliability and verification expectations.
- `quality/SECURITY.md`: security and privacy boundaries.
- `architecture/legacy-quarantine-audit.md`: legacy quarantine audit notes.

Keep this page compact. Add details to focused docs, not here.
