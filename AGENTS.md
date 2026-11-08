# FPVS Toolbox — Agent Rules

## Purpose and current state

The EEG processing pipeline is the primary product; analysis and visualization
tools consume its outputs. Prioritize correctness, reproducibility, extensibility,
and usability. The app uses PySide6, ships a Windows installer, and supports source
development on Windows 11 and CachyOS (Arch Linux).

Confirmed ActiveTwo64, ActiveThree, Brain Products and Unicorn projects have
scoped BIDS/MNE routes. Versioned method slots and persisted project selections
exist; each slot has one production method. Settings > Processing offers optional
guided setup. Alternative methods/selectors and complete FPVS Studio
interoperability remain future work. Read the
[roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md) for related
changes and the [hardware guide](docs/user/reference/eeg-hardware.md) for exact
format, montage and physical-qualification limits.

## Work and navigation

- Start with [agent-index](docs/agent/agent-index.md) for skills, audits and focused
  checks. Run the applicable audit before broad inspection; do not rescan a
  passing invariant. Repo-local skills govern this project; web skills apply only
  to explicitly web-scoped work.
- Read [ARCHITECTURE.md](ARCHITECTURE.md) before structural changes and the
  relevant [active plan](docs/agent/exec-plans/README.md) before a non-trivial
  refactor. Read focused contracts only for the affected area.
- State assumptions and ask when the safe interpretation is unclear. Make the
  smallest scoped change; preserve processing, formats, exports and workflows
  unless explicitly requested otherwise.
- Keep one portable implementation using `pathlib`, Python and PySide6;
  isolate OS-specific code to packaging/system integration. Use structured
  logging instead of production `print` calls.
- `src/Standalone_Scripts/**` is opt-in: do not list, search, read, run, import,
  edit or use it as precedent without explicit directory scope or user approval.
  Read its scoped `AGENTS.md` only after authorization. Exclude its tests from
  routine application verification.
- Unreferenced code is not automatically dead: check dynamic dispatch, Qt
  callbacks, public exports, compatibility aliases and persisted/pickle names
  before deletion. Preserve scientific baselines and historical-schema tests.
- Keep guidance current when ownership, boundaries, workflows or verification
  change; otherwise explain why no doc update is needed. Keep entry-point docs
  brief, link to canonical contracts, and use Git history for completed chronology.

## Canonical ownership

Use these owners for active imports; `Main_App.Shared` and `Main_App.Performance`
contain compatibility aliases only. Preserve their identity and public contracts;
do not add implementations there.

| Responsibility | Owner |
| --- | --- |
| EEG preprocessing | `Main_App.processing.preprocess` |
| BDF/common loading | `Main_App.io.load_utils` |
| GUI shell, workflows, widgets, styles | `Main_App.gui` |
| Shared GUI components | `Main_App.gui.components` |
| Workers and process runner | `Main_App.workers` |
| Project model, manager, roots, metadata, preprocessing settings | `Main_App.projects` |
| Processed-workbook discovery and group identity | `Main_App.projects.dataset_index`, via the public `Main_App.projects` surface |
| Application settings | `Main_App.settings` |
| Runtime diagnostics | `Main_App.diagnostics` |

Keep `settings.__init__` and `settings_paths` lightweight for the independent
updater; `settings_manager` is application-only. Repo checks belong in `scripts/`
or `.agents/`; manual project probes belong in `scripts/manual_diagnostics/`.
All project I/O uses the active project root and existing output formats.
Canonical groups come from participant metadata in `project.json`; downstream
tools must not infer membership from output folders or duplicate discovery logic.

## Protected boundaries and scientific contracts

- Do not recreate `src/Main_App/Legacy_App/**`, `src/Main_App/PySide6_App/**` or
  the retired `src/Tools/SourceLocalization/**`. Do not restore the latter's GUI,
  settings, tests, imports or quarantine dependencies without explicit restoration
  scope. Use current public APIs or thin adapters outside retired paths.
- The active `src/Tools/LORETA_Visualizer/` owns rendering, meshes, payloads,
  demo data and tool docs. Inverse calculations stay in `source_producers/`;
  renderer/payload helpers consume prepared values only. Do not bundle fsaverage
  data. Preserve the ignored root `.fpvs_cache/` MNE/fsaverage dependency cache
  during routine cleanup.
- Read the [loading contract](docs/agent/architecture/eeg-loading-contract.md)
  before loading/acquisition changes. Production reads cross project-local
  `io.bids_import`/`bids_loader` via `io.load_utils`. BDF/BVCDF samples stay
  unchanged; Unicorn permits only reviewed unit-header correction with originals
  and receipt retained. BVRF uses a labeled lossless FIF64 derivative, not standard
  raw EEG-BIDS. Numerical stages consume MNE Raw and immutable
  `io.recording_contract.RecordingContract`, never native readers/manufacturer
  dispatch. `io.acquisition_metadata` owns hardware defaults, geometry and
  qualification; `processing.acquisition_policy` is compatibility-only.
  Numerical reference/filter/interpolation stays in `processing`. Preserve
  precision, source metadata, canonical event samples and fingerprints through
  preflight, processing and cache reload; never edge-redecode canonical events.
  Unicorn remains eight scalp channels at 250 Hz, average reference, without
  interpolation or calibrated spatial QC. New hardware does not inherit QC
  qualification from this boundary.
- Read the [method contract](docs/agent/architecture/pipeline-methods.md) before
  dispatch/persistence changes. Keep fixed slots, application-registered method
  IDs, mandatory timing/geometry/review guards, checkpoints and condition repair.
  Never import code from project settings. Persist choices and explicitly
  invalidate affected results/caches; preserve default fingerprint identity.
- The Volfart-aligned preprocessing order is locked: initial reference → drop
  reference channels → optional channel limit preserving stim → FIR filter →
  downsample → kurtosis/interpolation → final average reference. Changing order,
  FIR duration scaling or version/fingerprint guards requires explicit
  statistical-method scope plus updates to the
  [preprocessing contract](docs/agent/architecture/preprocessing-contract.md),
  [methods checklist](docs/user/reference/methods-reporting-checklist.md) and
  focused order tests.
- Harmonic selection is locked by the
  [Stats contract](docs/agent/architecture/statistics-tools.md). Read it before
  selection, pooling, local-Z, summation or consumer changes. New projects persist
  `dzhelyova_poncet_two_consecutive_failures` v1 with all retained scalp channels;
  missing/unversioned existing profiles resolve to `legacy_fpvs_toolbox` v1.
  Preserve all four profiles, balanced non-legacy pooling, missing-cell failures,
  frozen masks, base-overlap exclusion, exact columns, strict `z > 1.64`,
  two-consecutive-failure stopping, and legacy-only gap/fill rules. The adaptive
  noise rule remains ±10 bins, excluding target±1 and target, dropping one finite
  minimum/maximum, then mean and population SD. Standard consumers use the exact
  canonical included list/fingerprint without reselection, refill or truncation.
  FHC independently consumes original FullFFT plus processing-owned provenance.
  Contract changes require explicit statistical-method scope and matching
  architecture, user-method and focused-test updates.
- Sensitivity Analysis remains input-only idealized design sensitivity under
  manually entered assumptions. Do not add project reads, observed residuals,
  fitted variance components, persistence or Stats coupling without separate
  data-informed feature scope. Do not call it observed/post-hoc power or
  model-fit validation.

## GUI and publication output

- Use PySide6 only; no Tkinter, CustomTkinter or CTkMessagebox. Import `QAction`
  from `PySide6.QtGui`.
- Long work uses `QThread` or `QRunnable`/`QThreadPool`. Workers signal results;
  they never touch widgets or block the UI thread.
- Start new/migrated surfaces from `gui.components`. Use its
  `SubsectionHeaderLabel`; shared typography belongs in `gui/widgets/labels.py`,
  not local QSS. `SectionCard` frames top-level subsections; keep parent
  containers flat and avoid nested cards unless requested.
- New/substantially revised embedded pages must fit 1280x900 without page-level
  scrolling. Split workflows into tabs/pages when needed. Tables, text viewers
  and focused dialogs may scroll.
- Follow the [figure standard](docs/agent/quality/figure-generation.md) when
  generating figures or adding figure tools. New general-purpose figures use
  the shared Nature-aligned defaults, paired PDF/PNG, and at least 600 DPI for
  raster export at the intended size. Keep figure typography independent of GUI
  typography and retain documented export profiles.

## Verification and handoff

Use existing `.venv1`, otherwise `.venv`; see
[development setup](docs/agent/guides/development.md). Run:

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

The driver owns test selection, audits, changed-file lint/compilation and the
bounded handoff gate. The full suite remains in CI. Documentation changes also
need the strict MkDocs build and link/owner checks in
[verification gates](docs/agent/quality/verification-gates.md#documentation-only-changes).

Never set `QT_QPA_PLATFORM=offscreen`, run offscreen scripts or run local
pytest-qt by default: they can hang. Qt execution is CI-only unless the user
explicitly approves a safe visible environment. GUI changes require non-GUI
checks and a documented visible/manual smoke path. Report unavailable gates,
reasons and residual risk. Use the
[pre-ship checklist](docs/agent/reviews/pre_ship_checklist.md) for final review.
