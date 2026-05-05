# Main App Folder Retirement Plan

## Goal

Retire the historical `Legacy_App` and `PySide6_App` package designations by moving active code into purpose-based `src/Main_App/` folders. The end state should make Main App ownership obvious to future agents and humans without changing FPVS processing behavior.

This plan governs package ownership and file moves only. The existing `docs/exec-plans/active/main-app-refactor.md` remains the broader Main App refactor record.

## Current Status

- Phase: inventory setup.
- Scope: documentation and future behavior-preserving package moves.
- First executable slice: inventory-only classification of tracked files under `src/Main_App/Legacy_App/` and `src/Main_App/PySide6_App/`.
- No code movement has started under this plan.

## Target Layout

Active Main App code should land in purpose-based folders:

- `Main_App.gui`
- `Main_App.gui.widgets`
- `Main_App.processing`
- `Main_App.io`
- `Main_App.projects`
- `Main_App.workers`
- `Main_App.diagnostics`
- `Main_App.exports`
- `Main_App.shared`

Temporary compatibility wrappers are allowed only when needed to keep a slice behavior-preserving. The final goal is to remove active imports of `Main_App.Legacy_App` and `Main_App.PySide6_App`.

## Classification Categories

Each tracked file under `src/Main_App/Legacy_App/` and `src/Main_App/PySide6_App/` must be classified before movement:

- Active implementation to move to a purpose-based package.
- Compatibility wrapper to delete after canonical imports are migrated.
- Replaced legacy code that should stay inactive until deletion is explicitly scoped.
- Dead code to remove after grep and focused checks prove it is unused.
- High-risk pipeline code that needs focused tests and contract docs before movement.

Record the chosen destination package, preservation checks, and any deletion rationale in this plan before implementing each move.

## Preservation Rules

Folder retirement must not change:

- preprocessing math, order, references, interpolation, filtering, event handling, or output formats
- BDF loading behavior, EXG typing, montage policy, memmap behavior, diagnostics, or unsupported-file behavior
- worker routing, signal payloads, queue behavior, cancellation, or threading
- project schema, project root behavior, generated paths, manifests, or dialogs
- post-processing math, Excel workbook names, sheet names, columns, formatting, FFT-neighbor rows, or export success behavior

Do not add new `Main_App.Legacy_App` or `Main_App.PySide6_App` imports. Existing compatibility imports should be migrated toward canonical purpose-based packages before old folders are removed.

## Initial Inventory Slice

The first slice under this plan is documentation-only:

1. Classify every tracked file under `src/Main_App/Legacy_App/`.
2. Classify every tracked file under `src/Main_App/PySide6_App/`.
3. Identify the canonical destination package for each active implementation.
4. Identify focused tests required before each high-risk move.
5. Record the next executable slice, likely low-risk GUI/widget implementation moves.

## Verification

For this documentation-only setup:

- `git diff --check`
- `python scripts/agent_audit.py`

For future movement slices, also run the focused tests for the touched domain and the relevant skill-local audits from `docs/agent-index.md`.

## Decisions

- Retiring the old folder names is a package-ownership refactor, not a behavior rewrite.
- `Legacy_App` is no longer a permanent protected black box; targeted edits or deletion are allowed only when documented and pipeline-preserving.
- `PySide6_App` is the current implementation source for many modules, but the package name should not remain the long-term architecture boundary.
- `main_window.py` has already been appropriately downsized. It may move to a new package path as part of folder retirement, but it should not be the target of another internal refactor unless explicitly requested.
