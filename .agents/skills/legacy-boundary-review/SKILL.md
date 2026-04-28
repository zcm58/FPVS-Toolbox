---
name: legacy-boundary-review
description: Use before refactors that may touch src/Main_App/Legacy_App/**, quarantined dead code, or code that must consume legacy behavior through public APIs or adapters only.
---

# Legacy Boundary Review

## Overview

Use this workflow when a task is near protected legacy modules or when it is unclear whether a change requires legacy edits. The default outcome is to keep protected modules untouched.

## Workflow

1. Run `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` before broad manual inspection.
2. Read only the focused docs or files needed by the task or by script failures.
3. Identify whether the requested behavior crosses a protected or quarantined path:
   - `src/Main_App/Legacy_App/**`
   - `src/Tools/SourceLocalization/**` is dead code and should stay empty of source files
   - `src/quarantine/**` is ignored quarantine, not active runtime
   - runtime-used legacy modules listed in the quarantine audit
4. Inspect existing public APIs, imports, adapters, and tests before proposing new boundaries.
5. Prefer a thin adapter or caller-side normalization outside protected folders.
6. If the needed change truly requires protected-module edits, stop and report why before editing.
7. Preserve behavior, processing order, and data formats from legacy code.
8. After changes, rerun `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py`.

## Checks

- Use `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` instead of manually scanning all protected paths.
- Confirm Source Localization was not revived unless explicitly requested.
- Confirm any adapter has focused tests around the boundary behavior.
- Confirm compatibility exports in `src/Main_App/__init__.py` are not changed accidentally.

## Response Requirements

- State which protected paths were evaluated.
- State whether protected modules were changed.
- List adapter or caller-side files changed.
- Include verification commands and results.
