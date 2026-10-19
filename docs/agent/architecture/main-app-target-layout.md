# Main App Target Layout

The purpose-based Main App package layout is implemented. Historical
`Legacy_App` and `PySide6_App` packages are retired; `Shared` and `Performance`
retain compatibility aliases. The next architectural direction is
[modular hardware/montages, processing composition, and complete Studio interoperability](hardware-pipeline-studio-roadmap.md),
built within these canonical owners.

## Target Shape

```text
src/Main_App/
  gui/            # Cross-platform PySide6 interface, widgets, menus, dialogs
  processing/     # EEG preprocessing and pipeline orchestration import surface
  io/             # BIDS admission, acquisition adapters, generic recording contract
  projects/       # Project model/settings, manifests, dataset identity/indexing
  workers/        # Qt workers, multiprocessing bridge, process runner
  diagnostics/    # Audits, event-time lock reports, debug/reporting helpers
  exports/        # Post-processing, workbook generation and publication styles
  settings/       # Application settings; initializer/path helpers are lightweight
  updates/        # GUI-neutral update protocol, downloads and installer handoff
```

## Migration Rules

- Move import surfaces before moving high-risk implementations.
- Keep temporary wrappers when they reduce breakage and make review boundaries
  clear.
- Do not change preprocessing math, processing order, project paths, exports, or
  generated file formats as part of layout moves.
- Update `ARCHITECTURE.md`, this target layout page, the focused contract page,
  and the active execution plan when ownership changes.

## Current State

`src/Main_App/processing/` is now the canonical Main App processing import
surface. It owns the stable no-op `process_data` coordinator plus raw-file
discovery, batch-file preparation, and compatibility processing-controller
helpers. It also owns the active preprocessing implementation while the
preprocessing contract and tests protect behavior. The shared MNE stages consume
generic recording metadata and project settings; numerical operations remain
here. `acquisition_policy.py` is a compatibility import shim. Acquisition
interpretation, native-format reading, and qualified spatial-profile metadata
belong upstream in `io`.
Multi-group batch discovery
uses all registered raw roots, carries stable group IDs through review and
incremental planning, computes condition/group output paths, and locks the
fingerprinted group layout after the first current-run grouped workbook.

`src/Main_App/io/` is now the canonical Main App I/O import surface. It owns the
shared exact-column/header XLSX reader used by processing and downstream tools,
while `Tools.Stats.io.xlsx_selected_reader` remains a compatibility adapter. It
also owns project-local BIDS preparation/reuse in `bids_import.py`, project-aware
MNE loading in `bids_loader.py`, the immutable generic `RecordingContract` in
`recording_contract.py`, acquisition resolution/calibrated profiles in
`acquisition_metadata.py`, and geometry identity adapters in `geometry_metadata.py`.
It retains BDF/Brain Products format adapters, file filters and resource paths.
See the [loading contract](eeg-loading-contract.md)
for the BVRF lossless-derivative exception and bounded header-only inspection.
`spectral_workbook.py` owns shared archive sessions and frequency-window reads;
`xlsx_xml.py` owns common XML decoding, while each reader retains its exact
selection, ordering, cache and error policy.

`src/Main_App/workers/` is now the canonical Main App worker import surface. It
owns the Qt worker, process runner, multiprocessing environment and compatibility
processing mixin implementations. Old `Performance` paths alias these same
module objects, preserving patching and historical pickle lookup.

`src/Main_App/projects/` is now the canonical Main App project import surface.
It owns the project model, project manager workflows, project metadata scanning,
projects-root helpers, and preprocessing settings normalization while project
I/O tests protect behavior during the package-layout migration. It also owns
canonical group and participant manifest normalization, immutable read-only
project group context, and safe group/output-folder helpers in
`projects/grouping.py`. `projects/dataset_index.py` owns the shared read-only
processed-workbook index, including workbook/condition discovery, participant
identity matching, canonical group assignment, duplicate preference, and
diagnostics. Stats, plotting, QC, and export tools consume that public project
API instead of importing another tool's scanner or detecting group IDs from
output folders.

`src/Main_App/gui/` is now the canonical Main App GUI import surface. It
owns project workflow orchestration, processing run start/stop/finalization
orchestration, GUI-side post-export completion handling, landing/main page
assembly, and shell/menu presentation helpers such as icons, header bar, file
menu, menu bar, and sidebar. It also owns the main-window shell, settings panel,
event-map behavior, style tokens, update manager, and reusable widgets while GUI
smoke tests protect behavior.

`src/Main_App/diagnostics/` is now the canonical Main App runtime diagnostics
owner. It contains preprocessing audit helpers and event-time lock reporting
while repo-evaluation scripts remain in `scripts/` and `.agents/skills/`.

`src/Main_App/exports/` is now the canonical Main App post-export adapter import
surface. It owns post-processing and workbook generation plus the adapter
that turns process/worker payloads into exports. The post-processing export
contract protects values, formats and publication behavior.

`src/Main_App/settings/` owns application settings and path resolution. Its
initializer and `settings_paths` stay independent of project, scientific and
GUI imports so the standalone updater remains isolated; `settings_manager`
is application-only and excluded from that bundle.

`Shared` and `Performance` now contain compatibility aliases only. Active source
imports canonical owners. Compatibility preserves module identity, logger
names, historical pickle globals and source/frozen resource roots; it is not
a second implementation. FFT crop helpers and ROI presets live in `processing`,
and user-message helpers live in `gui`.
