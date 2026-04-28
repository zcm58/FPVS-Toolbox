---
name: project-path-audit
description: Use when reviewing file I/O, project manifests, export/import paths, Windows paths, QFileDialog behavior, generated files, hard-coded path cleanup, or active project-root discipline.
---

# Project Path Audit

## Overview

Use this workflow for file dialogs, manifests, imports, exports, generated outputs, and any change that might read or write outside the active project root.

## Workflow

1. Run `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` before broad manual inspection.
2. Read only the focused docs or files needed by the task or by script failures.
3. Identify the active project root source for the workflow before changing path logic.
4. Find hard-coded absolute paths, home-directory assumptions, and current-working-directory assumptions in the touched workflow.
5. Replace unsafe joins with project-root-relative path construction.
6. Ensure user-selected paths cannot silently escape the intended project boundary when the workflow requires project-local outputs.
7. Handle `QFileDialog` Cancel without exceptions or stale state.
8. Preserve existing output formats, filenames, sheet names, and folder layout unless explicitly requested.
9. Cover missing, invalid, permission-denied, repeated-operation, and existing-file cases when they are realistic for the workflow.
10. Use `tmp_path` for tests and avoid depending on developer-machine paths.

## Checks

- Use `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` instead of manually scanning all paths.
- Confirm generated files land under the intended project root.
- Confirm dialog Cancel leaves the UI in a valid state.
- Run targeted project/file I/O tests before broader tests.

## Response Requirements

- State the project-root source used by the workflow.
- List any hard-coded paths removed or retained.
- State tests or manual path smoke steps.
- Include verification commands and results.
