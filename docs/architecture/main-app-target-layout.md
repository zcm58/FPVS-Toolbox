# Main App Target Layout

This page records the long-term Main App organization target. The goal is to
replace historical `Legacy_App` and `PySide6_App` naming with purpose-based
packages under `src/Main_App/`.

## Target Shape

```text
src/Main_App/
  gui/            # Windows/PySide6 user interface, widgets, menus, dialogs
  processing/     # EEG preprocessing and pipeline orchestration import surface
  io/             # BDF loading, project paths, manifests, export path helpers
  projects/       # Project model, project settings, project manager workflows
  workers/        # Qt workers, multiprocessing bridge, process runner adapters
  diagnostics/    # Audits, event-time lock reports, debug/reporting helpers
  exports/        # Post-processing/export adapters and export-facing helpers
  shared/         # Small cross-cutting helpers that do not fit a domain yet
  compatibility/  # Temporary wrappers for stale imports during migrations
```

## Migration Rules

- Move import surfaces before moving high-risk implementations.
- Keep temporary wrappers when they reduce breakage and make review boundaries
  clear.
- Do not change preprocessing math, processing order, project paths, exports, or
  generated file formats as part of layout moves.
- Update `ARCHITECTURE.md`, this target layout page, the focused contract page,
  and the active execution plan when ownership changes.

## Current First Step

`src/Main_App/processing/` is now the canonical Main App processing import
surface. It owns the stable no-op `process_data` coordinator plus raw-file
discovery, batch-file preparation, and compatibility processing-controller
helpers. It still delegates preprocessing to the existing PySide6 backend
implementation while the preprocessing contract and tests protect behavior.

`src/Main_App/io/` is now the canonical Main App BDF loader import surface. It
delegates to the existing shared loader implementation while the BDF loading
contract and tests protect behavior.

`src/Main_App/workers/` is now the canonical Main App worker import surface. It
delegates to the existing PySide6 worker and Performance process-runner
implementations while worker/threading tests protect behavior.

`src/Main_App/projects/` is now the canonical Main App project import surface.
It owns the project model, project manager workflows, project metadata scanning,
projects-root helpers, and preprocessing settings normalization while project
I/O tests protect behavior during the package-layout migration.

`src/Main_App/gui/` is now the canonical Main App GUI import surface. It
owns project workflow orchestration, processing run start/stop/finalization
orchestration, GUI-side post-export completion handling, and shell/menu
presentation helpers such as icons, header bar, file menu, and menu bar. It
delegates remaining main-window, settings-panel, sidebar, style-token, and
update-manager implementations while GUI smoke tests protect behavior.

`src/Main_App/diagnostics/` is now the canonical Main App runtime diagnostics
owner. It contains preprocessing audit helpers and event-time lock reporting
while repo-evaluation scripts remain in `scripts/` and `.agents/skills/`.

`src/Main_App/exports/` is now the canonical Main App post-export adapter import
surface. It owns the adapter that turns process/worker payloads into shared
post-processing exports while workbook generation remains protected by the
post-processing export contract.
