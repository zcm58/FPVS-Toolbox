---
name: cleanup-generated-files
description: Remove requested generated build, test, or tool artifacts from the FPVS Toolbox checkout while preserving project data and the local MNE/fsaverage dependency cache.
---

# Cleanup Generated Files

## Preview the requested scope

Use PowerShell on Windows or `pwsh` on CachyOS. The helper previews known
checkout-generated build, cache, and scratch targets. It skips tracked content,
linked paths, environments, project directories, and opt-in trees.

```powershell
& ./.agents/skills/cleanup-generated-files/scripts/cleanup_generated_files.ps1 -DryRun
```

Read the preview before deleting. Run the helper without `-DryRun` when
the user requested removal and every listed target is within scope. For a
narrower request, remove only the verified targets from the preview.

```powershell
& ./.agents/skills/cleanup-generated-files/scripts/cleanup_generated_files.ps1
```

Verify that the selected targets are gone and check `git status --short`.
Report skipped targets or access errors. If a file is locked, retry only
the authorized target after the lock clears.

## Preserve dependencies and project data

- Keep the checkout's root `.fpvs_cache/` for MNE/fsaverage, along with
  environments and IDE state, during routine cleanup. The retired bundled
  fsaverage directories and `src/fpvs_cache/` are distinct cleanup targets.
  Preserve active source and the rest of quarantine.
  [Garbage collection](../../../docs/agent/quality/garbage-collection.md)
- For Toolbox application or project caches, use the owning cache-maintenance
  workflow. It preserves recordings, exports, companions, project settings,
  review decisions, ledgers, and anatomical templates.
  [Cache maintenance](../../../docs/agent/architecture/cache-maintenance.md)
