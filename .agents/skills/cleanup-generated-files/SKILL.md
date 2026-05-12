---
name: cleanup-generated-files
description: Clean generated build artifacts, Python/tool caches, test scratch folders, and deprecated local data caches in FPVS Toolbox Repo. Use when the user asks to clean repo clutter, remove temp/cache files, clear build output, reclaim disk space, or delete stale generated folders such as build, site, __pycache__, .mypy_cache, .ruff_cache, .codex-tmp, test_tmp, src/fsaverage, or src/fpvs_cache.
---

# Cleanup Generated Files

## Workflow

1. State the cleanup scope before deleting anything.
2. Preserve `.venv1/`, `.idea/`, `src/quarantine/`, source files, docs, tests, and packaging scripts unless the user explicitly names them.
3. Run a dry run first:

```powershell
.\.agents\skills\cleanup-generated-files\scripts\cleanup_generated_files.ps1 -DryRun
```

4. If the user asked for deletion and the dry-run targets match the request, run:

```powershell
.\.agents\skills\cleanup-generated-files\scripts\cleanup_generated_files.ps1
```

5. Verify with:

```powershell
git status --short --ignored
```

## Guardrails

- Delete only ignored/generated artifacts or user-approved local data caches.
- Do not remove `src/quarantine/`; it is intentionally retained legacy reference material.
- Do not remove virtual environments unless the user explicitly identifies the stale environment.
- If deletion fails with permission errors, rerun the same script with escalation rather than broadening the command.
- Report any remaining permission-protected folders instead of silently skipping them.
