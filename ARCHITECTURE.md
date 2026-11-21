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

Confirmed ActiveTwo64, ActiveThree, Brain Products and Unicorn recordings use
project-local admission through `Main_App.io.load_utils`. The [loading contract](docs/agent/architecture/eeg-loading-contract.md#supported-project-routes)
owns the supported formats, sample preservation and qualification limits.
Numerical stages consume MNE Raw and an immutable recording contract.
[Versioned method slots](docs/agent/architecture/pipeline-methods.md) have one
production method each. Optional guided setup saves choices per project.

Studio exports protocol settings. Toolbox imports the supported subset into
a new project and retains provenance. Operators choose the hardware and EEG
recordings. The [handoff contract](docs/agent/architecture/project-io.md#studio-config-handoff)
owns the consumer format and identity rules. The [roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
tracks fuller interoperability and additional methods.

## Runtime Ownership

All paths below are under `src/`. Active imports use purpose-based packages.
For an action that spans a page, a worker and a backend, start with the
[desktop workflow guide](docs/agent/architecture/gui-backend.md). It maps the
GUI and backend owners and the regression checks for their shared behavior.

| Owner | Responsibility / contract |
| --- | --- |
| `main.py` | Main application launcher. |
| `Main_App/gui/` | Main-window coordination, workflow helpers, widgets, theme tokens, menus, update UI, and operation guards. Start new surfaces from `gui/components/`. Further `main_window.py` refactoring requires explicit scope. [GUI](docs/agent/architecture/gui.md) |
| `Main_App/processing/` | `preprocess.py`, stable `process_data`, processing controllers, neutral ROI settings and FullFFT provenance, harmonic selection and artifact freshness. [Preprocessing](docs/agent/architecture/preprocessing-contract.md) |
| `Main_App/io/` | Recording admission, geometry metadata, safe/atomic I/O, private memmaps, dense spectral/condition companions, and XLSX compatibility. `spectral_workbook.py` owns sessions/FullSNR windows; `xlsx_xml.py` owns XML cells. [Loading](docs/agent/architecture/eeg-loading-contract.md) |
| `Main_App/reporting/` | Opt-in lab results publishing, immutable retries, scoped identities and OS credentials. `Main_App.exports.reporting_csv` reads the released workbook. [Reporting agents](src/Main_App/reporting/AGENTS.md) |
| `Main_App/projects/` | Project model/manager, manifest transactions, metadata scanning, roots, preprocessing settings, group/participant identity, `dataset_index`, and [Studio config import](docs/agent/architecture/project-io.md#studio-config-handoff). Group membership comes from `project.json`; output folders only validate routing. [Project I/O](docs/agent/architecture/project-io.md) |
| `Main_App/exports/` | Post-processing/workbook export, worker adapter, and GUI-neutral figure/table style contracts. Heavy exports remain lazy. [Export contract](docs/agent/architecture/post-processing-export-contract.md), [figures](docs/agent/quality/figure-generation.md) |
| `Main_App/workers/` | Qt workers, process runner, multiprocessing environment, and compatibility processing mixin. [Threading](docs/agent/architecture/workers-threading.md), [mixin](docs/agent/architecture/processing-mixin-contract.md) |
| `Main_App/settings/` | App preferences and paths. Its initializer and `settings_paths` stay lightweight for the independent updater; `settings_manager` is application-only. |
| `Main_App/updates/`, `updater.py` | GUI-neutral update protocol, verified downloads/cache, installer handoff, and independently packaged Update & Repair. Source, tags, and new releases use `zcm58/FPVS-Toolbox`; historical release-only assets remain archived. [Updater](docs/agent/architecture/updater.md) |
| `Main_App/diagnostics/` | Runtime audit/event-time/log routing. Repo checks belong in scripts. [Diagnostics](docs/agent/architecture/diagnostics.md) |
| `Main_App/Shared/`, `Main_App/Performance/` | Same-object compatibility aliases only; preserve historical imports, monkeypatches, and pickle lookups without adding implementations. [Legacy boundaries](docs/agent/architecture/legacy-boundaries.md) |

`Main_App.io` resolves public names from their canonical modules on first
access. Resource paths, recording filename filters and result path helpers can
run in a fresh process without importing the EEG and table-reading libraries.

`projects.public_datasets` owns the anonymous OpenFPVS dataset wire contract.
`projects.experiment_library` validates immutable archives and installs portable
projects atomically. Its local receipts support offline reopening while preserving
local project edits. The GUI worker/controller opens the installed root through
the existing project workflow. See the [Library guide](docs/agent/guides/experiment-library.md).

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

## Repository Support

| Path | Role |
| --- | --- |
| `.agents/scripts/audit/`, `.agents/skills/` | Invariant checks and scoped agent workflows. |
| `.agents/scripts/verify.py`, `.agents/verification.toml` | Executable verification routing; `tests/qt_test_files.txt` identifies Qt coverage. |
| `tests/` | Unit/integration tests and CI Qt coverage. |
| `scripts/debug/`, `scripts/manual_diagnostics/`, `scripts/migration/` | Focused developer probes and migrations; not runtime APIs or default gates. |
| `scripts/packaging/` | Windows build/installer inputs. |
| `docs/agent/` | [Agent knowledge base](docs/agent/README.md) for internal engineering guidance. |
| `.github/workflows/` | Source and packaging CI. |

Optional quarantine and smoke directories may be absent. Do not create them
solely to satisfy an ownership map.

## Verification Strategy

[Test selection](docs/agent/quality/test-selection.md#scope-map) routes each
feature to its checks. [Verification gates](docs/agent/quality/verification-gates.md)
owns commands, documentation-only checks, CI Qt execution and failure reporting.
