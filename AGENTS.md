# FPVS Toolbox — Agent Rules

FPVS Toolbox processes recorded FPVS EEG. Analysis and visualization consume
its project-owned outputs. The maintained source runs on Windows 11 and CachyOS
(Arch Linux) and ships through a Windows installer.

## Find the owner

- Start with the [agent index](docs/agent/agent-index.md) for skills, first
  checks and focused scopes. Run the relevant audit before broader inspection.
  Read [ARCHITECTURE.md](ARCHITECTURE.md) for package and public import owners
  and the [active plan](docs/agent/exec-plans/README.md) for a non-trivial refactor.
- For desktop decisions use the [shared desktop direction](docs/agent/design-docs/DESIGN.md).
  For Studio exports, start with the [Toolbox handoff contract](docs/agent/architecture/project-io.md#studio-config-handoff).
  Toolbox imports supported configurations; operators identify the corresponding
  EEG. The [roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
  tracks further hardware, method and interoperability work.
- Read a tool's scoped `AGENTS.md` before editing it. Update the owning
  contract when a boundary, workflow or verification rule changes. Keep root
  guidance short and record completed chronology in Git.

## Working rules

- State assumptions and ask when the safe interpretation is unclear. Make
  the smallest scoped change that preserves workflows, processing, formats
  and exports. Keep paths and behavior portable with Python, `pathlib` and
  PySide6. Isolate packaging and system integration. Use structured logging.
- `src/Standalone_Scripts/**` is opt-in. Do not list, search, read, run,
  import, edit or use it as precedent unless the user scopes that directory
  or approves access. Only then read its instructions. Exclude its tests
  from routine verification.
- Before deleting seemingly unused code, check dynamic dispatch, Qt callbacks,
  public exports, compatibility aliases and persisted/pickle names. Preserve
  scientific baselines, historic schema tests and the identity of aliases in
  `Main_App.Shared` and `Main_App.Performance`.
- Keep `Main_App/Legacy_App`, `Main_App/PySide6_App` and `Tools/SourceLocalization`
  retired. Restoration requires explicit scope. Use the active public API or
  a thin adapter outside retired paths. In [LORETA Visualizer](src/Tools/LORETA_Visualizer/AGENTS.md),
  inverse calculations stay in `source_producers/`. Preserve the ignored
  `.fpvs_cache/` fsaverage dependency and keep it out of distributions.
- Use the active project root for I/O. Resolve processed data and group
  identity through `Main_App.projects.dataset_index` via the public
  `Main_App.projects` surface. Participant metadata in `project.json` owns
  group membership. [Project I/O](docs/agent/architecture/project-io.md)

## Scientific contracts

- [Recording admission](docs/agent/architecture/eeg-loading-contract.md#supported-project-routes)
  owns source preservation, approved derivatives, precision, geometry, events
  and qualification for each supported route. Processing consumes MNE Raw and
  its immutable recording contract. Keep native readers and hardware defaults
  upstream. Preserve canonical event samples and fingerprints across cache reload.
- [Pipeline methods](docs/agent/architecture/pipeline-methods.md) owns fixed
  versioned slots, registered methods, timing/geometry/review guards,
  checkpoints and invalidation. Preserve historical default fingerprints.
  Never load executable code from project settings.
- The [Volfart-aligned order](docs/agent/architecture/preprocessing-contract.md#pipeline-order)
  is locked, including FIR filtering before downsampling. Preserve FIR duration
  scaling, order and fingerprint guards.
- The [harmonic-selection contract](docs/agent/architecture/statistics-tools.md)
  locks all four profiles, pooling, masks, noise estimates, cutoffs and summation.
  New projects use `dzhelyova_poncet_two_consecutive_failures` v1 with all
  retained scalp channels. Missing or unversioned profiles in existing projects use `legacy_fpvs_toolbox`
  v1. Standard consumers use the exact selected list and fingerprint. FHC uses
  original FullFFT plus processing-owned provenance independently.
- Changing a locked method requires explicit scientific scope, updated
  architecture and user-facing method guidance, and focused regression tests.
- [Sensitivity Analysis](src/Tools/Sensitivity_Analysis/AGENTS.md) remains an
  input-only design-sensitivity calculator. Observed data, fitted variance,
  persistence and Stats coupling require separately scoped work.

## GUI and verification

- Use PySide6, shared `Main_App.gui.components` and `QtGui.QAction`. Follow
  the [layout rules](docs/agent/architecture/gui.md#visual-layout-rules) for
  flat sections and shared `SubsectionHeaderLabel` styling. The shell minimum
  is 1200 × 800. New or substantially revised embedded pages must fit the
  1280 × 900 workspace without page-level scrolling. Split controls into tabs
  or pages as needed. Tables, text viewers and focused dialogs may scroll.
- Follow [desktop workflow ownership](docs/agent/architecture/gui-backend.md).
  Keep prompts and worker lifetimes in the desktop. Run long operations in
  `QThread` or `QRunnable`/`QThreadPool` and signal results to widgets.
  Publication figures follow the separate [figure standard](docs/agent/quality/figure-generation.md).
- Use the [verification gates](docs/agent/quality/verification-gates.md) for
  focused and precommit commands, documentation-only changes and failure
  reporting. The driver selects the existing `.venv1` or `.venv`.
  Never use offscreen Qt locally. Qt runs in CI unless the user explicitly
  approves a safe visible environment. Document the visible smoke path and
  run non-GUI checks for GUI changes. [Pre-ship checklist](docs/agent/reviews/pre_ship_checklist.md)
