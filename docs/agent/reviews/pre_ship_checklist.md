# Pre-Ship Checklist

Use this before handing off non-trivial changes.

- Run the relevant command from `docs/agent/agent-index.md` before broad manual inspection.
- The diff is limited to the requested behavior and direct support files.
- Non-trivial refactors checked the relevant active plan in `docs/agent/exec-plans/active/`.
- Retired `Legacy_App` and `PySide6_App` paths were not recreated; any historical behavior cleanup preserves the processing pipeline, processing order, data formats, and exports.
- The historical `Tools.SourceLocalization` package remains retired; current
  LORETA Visualizer source producers retain their separate scoped boundary.
- GUI work uses PySide6 only and imports `QAction` from `PySide6.QtGui`.
- Long work is off the UI thread and workers do not touch widgets directly.
- Project file I/O uses the active project root and handles dialog Cancel paths.
- Existing data formats, filenames, sheet names, and processing order are preserved.
- Production diagnostics use logging rather than `print`.
- Targeted tests or smoke steps cover the changed behavior.
- Architecture docs or the nearest scoped `AGENTS.md` were updated for changed structure, ownership, boundaries, workflows, or verification expectations.
- If no doc update was needed, the handoff or active execution plan explains why.
- Any skipped verification is explained with residual risk.

For acquisition, montage, processing-plan or Studio integration changes, also
apply the [roadmap](../architecture/hardware-pipeline-studio-roadmap.md):

- State the supported device/montage and Studio schema/version combination;
  distinguish implemented inspection, production support and qualification.
- Preserve the locked BioSemi baseline; stage selection must use explicit
  capabilities and versioned identities, with unsupported operations blocked.
- Verify units, channel roles/geometry/order, source event/sample coordinates,
  cache/provenance separation and canonical project identities end to end.
- Record paired Studio producer/Toolbox consumer fixture results before claiming
  compatibility. Do not invent fields or infer support for untested versions.
- Keep source regression, automated installer, human visible review and
  hardware/scientific validation results separate.
