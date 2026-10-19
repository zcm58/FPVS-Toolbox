---
name: legacy-boundary-review
description: Use before refactors that may touch retired src/Main_App/Legacy_App/** references, removed/dead feature boundaries, or code that must consume historical behavior through public APIs or adapters only.
---

# Legacy Boundary Review

## Overview

Use this workflow when a task is near retired `Legacy_App` references or when it is unclear whether a change consumes historical behavior. The default outcome is to preserve processing behavior exactly while moving callers or small responsibilities toward clearer current-app modules.

## Workflow

1. Use the active `.venv1` or `.venv` described in `docs/agent/guides/development.md`.
2. Run `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` before broad manual inspection.
3. Read only the focused docs or files needed by the task or by script failures.
4. Identify whether the requested behavior crosses a retired-path, historical-boundary, or removed-feature path:
   - `src/Main_App/Legacy_App/**` is retired and must not be recreated
   - `src/Main_App/PySide6_App/**` is retired and must not be recreated
   - the historical Source Localization/eLORETA package is removed; `src/Tools/SourceLocalization/**` should stay empty of source files
   - the separate current `src/Tools/LORETA_Visualizer/` owns prepared-payload rendering and isolated `source_producers/`; use its scoped contracts rather than retired code
   - `src/quarantine/**`, when present, is ignored quarantine, not active runtime
   - `Main_App.Shared` and `Main_App.Performance` are same-object compatibility aliases; active implementations and imports belong in purpose-based packages
5. Inspect existing public APIs, imports, adapters, and tests before proposing new boundaries.
6. Prefer a thin adapter, caller-side normalization, or current-app module when that preserves behavior.
7. Do not recreate retired package paths; if historical behavior is needed, use existing current-app APIs or a focused adapter outside the retired path.
8. Preserve behavior, processing order, data formats, exports, and user workflows from historical code.
9. After changes, rerun `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py`.

## Checks

- Use `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` instead of manually scanning all protected paths.
- Confirm the retired Source Localization package was not revived; preserve the
  current Visualizer/source-producer boundary.
- Confirm any adapter has focused tests around the boundary behavior.
- Confirm compatibility exports in `src/Main_App/__init__.py` are not changed accidentally.
- Confirm retired `Legacy_App` and `PySide6_App` paths were not recreated.

For hardware, montage, pipeline-stage, or FPVS Studio changes, first read the
[shared roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md).
Modularity is a target for explicit versioned capabilities, not permission to
reorder locked BioSemi processing or enable unqualified spatial methods. Keep
existing compatibility aliases and historical project behavior while extending
the canonical owners.

## Response Requirements

- State which protected paths were evaluated.
- State whether retired `Legacy_App` or `PySide6_App` paths were affected and why the processing pipeline is unchanged.
- List adapter or caller-side files changed.
- Include verification commands and results.
