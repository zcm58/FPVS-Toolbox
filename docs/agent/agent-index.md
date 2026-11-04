# Agent Index

Choose the task row, run its first check, then read only the relevant contract.
Do not rescan broad folders to reconfirm passing invariants. Root
[AGENTS.md](../../AGENTS.md) owns rules; [ARCHITECTURE.md](../../ARCHITECTURE.md)
owns the package map. Exclude `src/Standalone_Scripts/**` from all routine
inspection and execution unless explicitly scoped or approved.

## First Commands

Use the existing `.venv1`, otherwise `.venv`; the verification driver selects
that interpreter. See [development](guides/development.md) for shell setup.

| Task | Initial check |
| --- | --- |
| General invariants | `python .agents/scripts/audit/agent_audit.py` |
| GUI imports/toolkit boundaries | `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` |
| Retired/protected paths | `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` |
| Project paths, file I/O, exports | `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` |
| Stats structure or reporting legibility | `python .agents/scripts/audit/agent_audit.py --check stats-structure` or `--check stats-reporting-legibility` |
| Generated-file cleanup | `python .agents/scripts/audit/agent_audit.py --check garbage-collection` |
| Feature verification | `python .agents/scripts/verify.py --scope <scope> --tier focused`; select a [scope](quality/test-selection.md#scope-map). |

## Skill Map

Repo-local skills take precedence for this repo. Web/frontend skills apply
only to explicitly web-scoped work, not the PySide6 desktop GUI.

| Task | Skill | Focused contract |
| --- | --- | --- |
| PySide6 widgets, menus, workers, orchestration, status | `pyside6-gui-cleanup` | [GUI](architecture/gui.md), [threading](architecture/workers-threading.md) |
| Updater/downloads/installers | `project-path-audit`; GUI skill for changed surfaces | [Updater](architecture/updater.md) |
| Package ownership/retired boundaries | `legacy-boundary-review` | [Target layout](architecture/main-app-target-layout.md), [legacy](architecture/legacy-boundaries.md) |
| Preprocessing entry points/order | `legacy-boundary-review`; GUI skill for orchestration | [Preprocessing](architecture/preprocessing-contract.md) |
| Removed-electrode or kurtosis calibration | `legacy-boundary-review` | [Removed electrodes](quality/removed-electrode-detection-calibration.md), [kurtosis](quality/kurtosis-screening-calibration.md) |
| Recording loading/memmaps | `legacy-boundary-review` + `project-path-audit` | [Loading](architecture/eeg-loading-contract.md) |
| Hardware/montages, pipeline methods, Studio | `project-path-audit`; processing/GUI skills as affected | [Roadmap](architecture/hardware-pipeline-studio-roadmap.md), [methods](architecture/pipeline-methods.md), [Project I/O](architecture/project-io.md) |
| Post-processing/FFT crop/export | `legacy-boundary-review` | [Exports](architecture/post-processing-export-contract.md), [crop](architecture/fft-crop-method.md) |
| Manifests, project roots, dialogs/imports | `project-path-audit` | [Project I/O](architecture/project-io.md) |
| Publication figures | `project-path-audit` | [Figure standard](quality/figure-generation.md) |
| Stats | `pyside6-gui-cleanup` for GUI changes; focused Stats tests | [Statistics/tools](architecture/statistics-tools.md), scoped `src/Tools/Stats/AGENTS.md` |
| Free Harmonic Clustering | `project-path-audit` | [Scoped rules](../../src/Tools/Free_Harmonic_Clustering/AGENTS.md), [architecture](../../src/Tools/Free_Harmonic_Clustering/ARCHITECTURE.md) |
| LORETA Visualizer | `legacy-boundary-review` | [Scoped rules](../../src/Tools/LORETA_Visualizer/AGENTS.md), [architecture](../../src/Tools/LORETA_Visualizer/ARCHITECTURE.md) |
| Scalp Maps / Sequence Figure | `pyside6-gui-cleanup` + `project-path-audit` | [Scalp Maps](../../src/Tools/Publication_Maps/AGENTS.md), [Sequence Figure](../../src/Tools/Sequence_Figure/AGENTS.md) |
| Publication tables | `publication-table-export` + `project-path-audit` | [Skill](../../.agents/skills/publication-table-export/SKILL.md) |
| Qt smoke definitions | `pytest-qt-smoke` | [Test selection](quality/test-selection.md); execution is CI-only by default |
| Generated files/caches | `cleanup-generated-files` | [Cleanup](quality/garbage-collection.md), [debt](exec-plans/tech-debt-tracker.md) |
| Pressure-testing a plan | `grillme` | Inspect locally answerable questions first; ask one question at a time |

## Execution Plans

Read the matching active plan before changing its area. The
[plan index](exec-plans/README.md) owns status and remaining acceptance.
Future plans are read only when scoping that work; completed implementation
history is not routine context. Installer evidence belongs to the
[v3 release ledger](exec-plans/active/v3-release-readiness.md), not later source.

| Area | Plan / verification route |
| --- | --- |
| BIDS/shared processing | [BIDS](exec-plans/active/bids-shared-pipeline.md), [multi-hardware](exec-plans/active/multi-hardware-bids.md); `project-io` and `processing` as affected |
| Fixed method slots/selections/cache identity | [Modular methods](exec-plans/active/modular-processing-methods.md); `pipeline-methods` |
| Guided setup/draft/save workflow | [Guided setup](exec-plans/active/guided-pipeline-setup.md); `pipeline-setup` and `gui` |
| Hardware/Studio extensions | [Roadmap](architecture/hardware-pipeline-studio-roadmap.md), then the matching plan; physical qualification stays separate |

## Test Selection

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Run the affected focused scope first. Precommit runs all invariants, changed
Python lint/compile checks, bounded repo tests, and changed non-Qt tests; it
does not infer feature scopes or run the full suite. The executable registry is
`.agents/verification.toml`; the complete [scope map](quality/test-selection.md#scope-map)
includes `pipeline-setup`. See [verification gates](quality/verification-gates.md)
for docs-only checks and failure reporting.

Qt runs in CI unless the user explicitly approves a safe visible environment.
Never set `QT_QPA_PLATFORM=offscreen` or run ad-hoc offscreen Qt locally.
GUI changes need non-GUI checks and a documented visible/manual smoke path.

## Manual Diagnostics

`scripts/debug/` and `scripts/manual_diagnostics/` contain developer probes;
`scripts/packaging/` owns releases. Optional `.agents/scripts/smoke/` probes
are not default gates, and that directory may be absent.

BIDS comparison scripts run only for an explicitly scoped old/new comparison,
not a routine gate; see the BIDS plan. Real-project probes require their own
new diagnostic output directory and must preserve source manifests/results.

FHC focused tests include the deterministic 24 x 199 regression smoke. Its
4,000 x 10,000 powered calibration is separate manual work under the
[frozen protocol](quality/free-harmonic-clustering-null-calibration.md);
never launch it as routine pytest/precommit or present a partial run as
completed acceptance.
