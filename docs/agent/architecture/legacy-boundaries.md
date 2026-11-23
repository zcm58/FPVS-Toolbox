# Legacy Boundaries

Keep these retired import roots absent from the source tree.

- `src/Main_App/Legacy_App/**`
- `src/Main_App/PySide6_App/**`
- `src/Tools/SourceLocalization/**`

Git history preserves the migration code. Removing remnants from a checkout is
ordinary cleanup. Reintroducing any retired package or same-named module
requires explicit restoration scope and updated ownership and verification.
Active Main App behavior belongs in purpose-based packages such as
`Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.exports`,
`Main_App.workers`, `Main_App.diagnostics`, and `Main_App.gui`.

### Source localization

- The current `src/Tools/LORETA_Visualizer/**` is a separate active tool.
  Its scoped contracts govern the active L2-MNE and eLORETA methods.
- In that separate tool, renderer and payload helpers display or adapt prepared
  values only. Existing calculations belong in its isolated `source_producers/`
  package, including the normal Hauk-informed L2-MNE source-PSD path and
  legacy/exploratory workbook producers. Do not move inverse solutions or source
  statistics into renderer, mesh, payload, or GUI helpers.
- The visualizer may fetch external fsaverage data through MNE, but durable
  automatic installs belong in the ignored repository-root `.fpvs_cache`
  directory, never in active source, docs, package data, or quarantine paths.

### Compatibility

- Use the canonical runtime owners for new calls. Put any needed adapters or
  caller-side normalization in active packages.
- Keep the same-object `Main_App.Shared.*` and `Main_App.Performance.*` aliases
  and the top-level `Main_App` compatibility exports. They support existing
  imports, monkeypatches, and pickle lookups.
- Keep the retired Source Localization implementation and optional quarantine
  outside active runtime. Scope LORETA work to its current [tool rules](../../../src/Tools/LORETA_Visualizer/AGENTS.md).

### Verification

```console
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/scripts/verify.py --scope legacy-boundary --tier focused
```

The wrapper checks the current checkout for the retired import paths and scans
added Python lines for retired Source Localization references. Pass
`--base-ref <revision>` to the wrapper for a committed comparison. The focused
scope also verifies the live compatibility imports.
