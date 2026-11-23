---
name: project-path-audit
description: Audit FPVS Toolbox project roots, persisted paths, import and export destinations, managed file writes, and file picker behavior.
---

# Project Path Audit

## First check

Run the path audit with the [repo interpreter](../../../docs/agent/guides/development.md) before broad inspection.

```console
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

The wrapper selects the central `paths` check. It scans added lines and
eligible untracked files for local path literals. Pass `--base-ref <revision>`
or set `FPVS_AGENT_AUDIT_BASE_REF` to include committed changes. The default
comparison is `HEAD`. Inspect the affected workflow for dynamic paths,
containment, portable serialization, and cancellation even when the check
passes. [Verification gates](../../../docs/agent/quality/verification-gates.md#ci-change-detection)

## Follow the workflow owner

- Anchor managed project I/O in the runtime `Project.project_root`. It comes
  from the opened project directory. For tools with the standard fallback,
  `Main_App.projects.resolve_active_project_root` checks the explicit root,
  `FPVS_PROJECT_ROOT`, then the current project. Preserve stricter tool-specific
  entry points and avoid using the process working directory as a fallback.
  [Project I/O](../../../docs/agent/architecture/project-io.md)
- Identify the destination before changing a join. Project-managed artifacts
  follow their configured root and containment rules. Preserve supported
  external raw/result roots and explicit export destinations. App settings,
  updater staging, and app caches follow their respective owners. Preserve
  existing formats, filenames, sheets, and layout.
  [Settings storage](../../../docs/agent/architecture/project-io.md#settings-storage) ·
  [Cache maintenance](../../../docs/agent/architecture/cache-maintenance.md) ·
  [Updater](../../../docs/agent/architecture/updater.md)
- Use `Main_App.projects.load_project_dataset_index` for processed records and
  canonical identities. The index takes group assignments from project metadata
  and checks output folders against those assignments. Keep the NumPy companion
  references in native `.fpvs` manifests as validated sibling basenames and
  retain historical XLSX discovery.
  [Multi-group foundation](../../../docs/agent/architecture/project-io.md#multi-group-processing-foundation) ·
  [Native results](../../../docs/agent/architecture/post-processing-export-contract.md#native-condition-results)
- Verify resolved containment for project-local writes or cleanup, including
  symlink or junction targets where relevant. Use `pathlib` for runtime joins
  and the format owner's rules for persisted relative paths. Hold
  `project_manifest_transaction` across project manifest read, validation,
  update, and publish. Reuse the owning safe-file or atomic-write boundary.
  [Manifest transactions](../../../docs/agent/architecture/project-io.md#manifest-transactions)
- For Studio or hardware imports, check the actual versioned producer contract
  and the Toolbox support limits. Preserve source and recording identity,
  timing, units, provenance, and historical inputs.
  [Studio handoff](../../../docs/agent/architecture/project-io.md#studio-config-handoff) ·
  [Hardware roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)

## Verify the affected boundary

For runtime project I/O changes, start with the focused scope.

```console
python .agents/scripts/verify.py --scope project-io --tier focused
```

Use isolated project fixtures for relevant cases such as copied roots,
Windows and Linux path forms, external destinations, denied access, or
replacement of existing files. For picker changes, verify Cancel preserves
the previous state and document a visible smoke path. Qt execution stays in
CI unless the user approves a safe visible local session.
[Test selection](../../../docs/agent/quality/test-selection.md)

Report the workflow's root and destination, path findings, and checks run.
