# Architecture

Use this map for ownership; use the [agent index](docs/agent/agent-index.md)
for commands, skills, and focused reading. Root [AGENTS.md](AGENTS.md) owns
working rules and scientific protections. Read the matching
[active plan](docs/agent/exec-plans/README.md) before changing its area. Update
the relevant contract when ownership, boundaries, workflows, or verification
change; otherwise state why no documentation update was needed.

## Application Shape

FPVS Toolbox is a PySide6 desktop application. Its primary product is the EEG
processing pipeline; analysis and visualization tools consume its outputs.
Windows installers are the release deliverable; shared source also supports
CachyOS. Release tags and acceptance receipts define shipped behavior.

Current acquisition routes cover confirmed ActiveTwo64, ActiveThree, Brain
Products, and Unicorn within the [hardware guide's](docs/user/reference/eeg-hardware.md)
format and qualification limits. Production reads enter
`Main_App.io.bids_import` / `bids_loader` through `io.load_utils`, producing
MNE Raw and an immutable `io.recording_contract.RecordingContract`.
`io.acquisition_metadata` resolves hardware defaults and qualified capabilities;
`io.geometry_metadata` owns geometry identity. Numerical reference, filtering,
resampling, interpolation, and QC stay in `processing`; they do not dispatch
native readers or resolve manufacturers.

BDF/BVCDF signal bytes are preserved. Unicorn permits only the reviewed
unit-header correction, retains originals and its receipt, and stays at eight
scalp channels, 250 Hz, average reference, with no interpolation or calibrated
spatial QC. BVRF uses a labeled lossless FIF64 derivative, not standard raw
EEG-BIDS. `io.pipeline_events` carries canonical sample events through preflight,
processing, and cache reload. See the [loading contract](docs/agent/architecture/eeg-loading-contract.md).

`processing.pipeline_plan` owns fixed versioned method slots and persisted
selections; each slot currently has one production method. Implementations
remain at their numerical owners and defaults preserve historical fingerprints.
Optional guided setup uses `projects.pipeline_setup` for the detached draft,
`gui.pipeline_setup_dialog` for worker-backed saving, and
`gui.pipeline_setup_workflow` for launch guards. Alternative methods/selectors
and complete Studio interoperability remain future work. See
[method contracts](docs/agent/architecture/pipeline-methods.md) and the
[current-state/future roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md).

## Runtime Ownership

All paths below are under `src/`. Active imports use purpose-based packages.

| Owner | Responsibility / contract |
| --- | --- |
| `main.py` | Main application launcher. |
| `Main_App/gui/` | Main-window coordination, workflow helpers, widgets, theme tokens, menus, update UI, and operation guards. Start new surfaces from `gui/components/`. Further `main_window.py` refactoring requires explicit scope. [GUI](docs/agent/architecture/gui.md) |
| `Main_App/processing/` | `preprocess.py`, stable `process_data`, processing controllers, neutral ROI settings and FullFFT provenance, harmonic selection and artifact freshness. [Preprocessing](docs/agent/architecture/preprocessing-contract.md) |
| `Main_App/io/` | Recording admission, geometry metadata, safe/atomic I/O, private memmaps, dense spectral/condition companions, and XLSX compatibility. `spectral_workbook.py` owns sessions/FullSNR windows; `xlsx_xml.py` owns XML cells. [Loading](docs/agent/architecture/eeg-loading-contract.md) |
| `Main_App/projects/` | Project model/manager, manifest transactions, metadata scanning, roots, preprocessing settings, group/participant identity, `dataset_index`, and [Studio config import](docs/agent/architecture/project-io.md#studio-config-handoff). Group membership comes from `project.json`; output folders only validate routing. [Project I/O](docs/agent/architecture/project-io.md) |
| `Main_App/exports/` | Post-processing/workbook export, worker adapter, and GUI-neutral figure/table style contracts. Heavy exports remain lazy. [Export contract](docs/agent/architecture/post-processing-export-contract.md), [figures](docs/agent/quality/figure-generation.md) |
| `Main_App/workers/` | Qt workers, process runner, multiprocessing environment, and compatibility processing mixin. [Threading](docs/agent/architecture/workers-threading.md), [mixin](docs/agent/architecture/processing-mixin-contract.md) |
| `Main_App/settings/` | App preferences and paths. Its initializer and `settings_paths` stay lightweight for the independent updater; `settings_manager` is application-only. |
| `Main_App/updates/`, `updater.py` | GUI-neutral update protocol, verified downloads/cache, installer handoff, and independently packaged Update & Repair. Source, tags, and new releases use `zcm58/FPVS-Toolbox`; historical release-only assets remain archived. [Updater](docs/agent/architecture/updater.md) |
| `Main_App/diagnostics/` | Runtime audit/event-time/log routing. Repo checks belong in scripts. [Diagnostics](docs/agent/architecture/diagnostics.md) |
| `Main_App/Shared/`, `Main_App/Performance/` | Same-object compatibility aliases only; preserve historical imports, monkeypatches, and pickle lookups without adding implementations. [Legacy boundaries](docs/agent/architecture/legacy-boundaries.md) |

`processing.harmonic_settings` and `processing.canonical_harmonics` own shared
versioned harmonic settings and accepted selections; former Stats modules are
compatibility exports. Processing, Stats, LORETA, and heavy export entry points
must retain lazy loading so backend contracts do not require GUI initialization.
`processing.processing_history` reads saved completed-run time and participant
identity for the asynchronous Home summary; it never infers them from output dates.
See the [target layout](docs/agent/architecture/main-app-target-layout.md) and
[module map](docs/agent/architecture/module-map.md) for deeper navigation.

## Tool Boundaries

Tools under `src/Tools/` open through the Main App GUI. Read their scoped
`AGENTS.md` before edits; common ownership is in
[Statistics and Tools](docs/agent/architecture/statistics-tools.md).

| Tool | Boundary |
| --- | --- |
| Stats, Plot Generator, Publication Maps, Individual Detectability | Consume canonical project data/identity and accepted processing outputs; preserve their scoped scientific and export contracts. |
| Sequence Figure | Widget-free renderer for manually selected stimulus illustrations; PNG/PDF/SVG exports, separate from SNR plots. |
| Sensitivity Analysis | Input-only idealized design sensitivity, including cancellable mixed-model simulation. No observed/post-hoc power, fitted-data validation, project-data reads, persistence, or Stats coupling. |
| Free Harmonic Clustering | GUI-neutral preparation/inference/exports with a thin project-bound workspace. Uses original FullFFT and processing-owned provenance, never the standard selected harmonic list or Summed BCA. [Tool architecture](src/Tools/Free_Harmonic_Clustering/ARCHITECTURE.md) |
| LORETA Visualizer | Renderer/meshes/payload adapters consume prepared values. Existing L2-MNE/eLORETA calculations stay isolated in `source_producers/`; never bundle fsaverage. [Tool architecture](src/Tools/LORETA_Visualizer/ARCHITECTURE.md) |

## Boundaries

- Preserve locked preprocessing order, harmonic-selection profiles, fingerprints,
  formats, and project workflows under root `AGENTS.md` and their focused contracts.
- GUI code owns widgets/signals; long work runs in workers, which never touch
  widgets. Prefer one portable implementation and isolate necessary OS behavior.
- Project I/O uses the opened `Project.project_root`; downstream discovery uses
  the public `Main_App.projects` index. See [Project I/O](docs/agent/architecture/project-io.md).
- `Main_App/Legacy_App`, `Main_App/PySide6_App`, and `Tools/SourceLocalization`
  are retired; do not recreate them or import quarantine implementations.
  Preserve the ignored root `.fpvs_cache` MNE/fsaverage dependency cache.
- `src/Standalone_Scripts/` is opt-in: no listing, search, reading, execution,
  import, edits, or precedent without explicit scope/approval. Optional quarantine
  and smoke directories need not exist; do not create them to satisfy a map.

## Repository Support

| Path | Role |
| --- | --- |
| `.agents/scripts/audit/`, `.agents/skills/` | Invariant checks and scoped agent workflows. |
| `.agents/scripts/verify.py`, `.agents/verification.toml` | Executable verification routing; `tests/qt_test_files.txt` identifies Qt coverage. |
| `tests/` | Unit/integration tests and CI Qt coverage. |
| `scripts/debug/`, `scripts/manual_diagnostics/`, `scripts/migration/` | Focused developer probes and migrations; not runtime APIs or default gates. |
| `scripts/packaging/` | Windows build/installer inputs. |
| `docs/agent/`, `docs/user/` | [Agent knowledge base](docs/agent/README.md) and user MkDocs source. |
| `.github/workflows/` | Source/packaging CI and strict documentation deployment from `main`. |

## Verification Strategy

Run the relevant focused scope, then the lightweight repo precommit gate.
The full suite and Qt execution remain in CI by default; local GUI changes need non-GUI
checks and a documented visible smoke path. Never run local offscreen Qt.
[Test selection](docs/agent/quality/test-selection.md) owns scope routing;
[verification gates](docs/agent/quality/verification-gates.md) owns commands,
documentation-only checks, CI behavior, and failure reporting.
