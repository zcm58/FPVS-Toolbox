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

`src/Main_App/processing/` is now the canonical Main App preprocessing import
surface. It delegates to the existing PySide6 backend implementation while the
preprocessing contract and tests protect behavior.

`src/Main_App/io/` is now the canonical Main App BDF loader import surface. It
delegates to the existing shared loader implementation while the BDF loading
contract and tests protect behavior.

`src/Main_App/workers/` is now the canonical Main App worker import surface. It
delegates to the existing PySide6 worker and Performance process-runner
implementations while worker/threading tests protect behavior.

`src/Main_App/projects/` is now the canonical Main App project import surface.
It delegates to the existing project model, project manager, project metadata,
projects-root, and preprocessing-settings implementations while project I/O
tests protect behavior.

`src/Main_App/gui/` is now the canonical Main App GUI import surface. It
delegates to the existing main-window, settings-panel, menu, sidebar, icon,
style-token, and update-manager implementations while GUI smoke tests protect
behavior.
