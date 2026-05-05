---
name: legacy-boundary-review
description: Use before refactors that may touch src/Main_App/Legacy_App/**, removed/dead feature boundaries, or code that must consume legacy behavior through public APIs or adapters only.
---

# Legacy Boundary Review

## Overview

Use this workflow when a task is near the `Legacy_App` migration boundary or when it is unclear whether a change requires edits to runtime-used legacy modules. The default outcome is to preserve processing behavior exactly while moving callers or small responsibilities toward clearer current-app modules.

## Workflow

1. Run `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` before broad manual inspection.
2. Read only the focused docs or files needed by the task or by script failures.
3. Identify whether the requested behavior crosses a migration-boundary or removed-feature path:
   - `src/Main_App/Legacy_App/**`
   - Source Localization/eLORETA is removed from active runtime; `src/Tools/SourceLocalization/**` should stay empty of source files
   - `src/quarantine/**` is ignored quarantine, not active runtime
   - runtime-used legacy modules listed in the quarantine audit
4. Inspect existing public APIs, imports, adapters, and tests before proposing new boundaries.
5. Prefer a thin adapter, caller-side normalization, or current-app module when that preserves behavior.
6. Targeted edits inside `Legacy_App` are allowed for active refactors, but first state why the edit is needed and how the processing pipeline remains unchanged.
7. Preserve behavior, processing order, data formats, exports, and user workflows from legacy code.
8. After changes, rerun `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py`.

## Checks

- Use `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` instead of manually scanning all protected paths.
- Confirm Source Localization/eLORETA was not revived unless explicitly requested.
- Confirm any adapter has focused tests around the boundary behavior.
- Confirm compatibility exports in `src/Main_App/__init__.py` are not changed accidentally.
- Confirm any `Legacy_App` edit is covered by a targeted test or documented smoke path.

## Response Requirements

- State which protected paths were evaluated.
- State whether `Legacy_App` modules were changed and why the processing pipeline is unchanged.
- List adapter or caller-side files changed.
- Include verification commands and results.
