# Agent Index

Choose the task row and run its first check. [Root rules](../../AGENTS.md)
govern inspection and scientific protections. [ARCHITECTURE.md](../../ARCHITECTURE.md)
maps package ownership. For desktop experience decisions, start with the
[shared design guide](design-docs/DESIGN.md).

## First Commands

Use the existing `.venv1`, otherwise `.venv`; the verification driver selects
that interpreter. See [development](guides/development.md) for shell setup.

| Task | Initial check |
| --- | --- |
| General invariants | `python .agents/scripts/audit/agent_audit.py` |
| GUI imports/toolkit boundaries | `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` |
| Retired import paths | `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` |
| New local path literals | `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` |
| Stats structure or reporting legibility | `python .agents/scripts/audit/agent_audit.py --check stats-structure` or `--check stats-reporting-legibility` |
| Study analysis from FPVS data | Check the source export, analysis grain and participant coverage with [fpvs-analysis](../../.agents/skills/fpvs-analysis/SKILL.md). |
| Generated-file cleanup | `python .agents/scripts/audit/agent_audit.py --check garbage-collection` |
| Feature verification | `python .agents/scripts/verify.py --scope <scope> --tier focused`; select a [scope](quality/test-selection.md#scope-map). |

## Skill Map

Repo-local skills take precedence for this repo. Web/frontend skills apply
only to explicitly web-scoped work, not the PySide6 desktop GUI.

| Task | Skill or verification scope | Focused contract |
| --- | --- | --- |
| PySide6 widgets, menus, workers, orchestration, status | `pyside6-gui-cleanup` | [GUI](architecture/gui.md), [threading](architecture/workers-threading.md) |
| Separating a desktop action from project, processing or tool code | `pyside6-gui-cleanup`; start with the owning feature scope | [Workflow owners and regression checks](architecture/gui-backend.md) |
| Updater/downloads/installers | `project-path-audit`; GUI skill for changed surfaces | [Updater](architecture/updater.md) |
| Public Experiment Library | `pyside6-gui-cleanup` + `project-path-audit`; `gui` and `project-io` scopes | [Implementation and acceptance](exec-plans/active/public-experiment-library.md), [workflow guide](guides/experiment-library.md) |
| Package ownership/retired boundaries | `legacy-boundary-review` | [Target layout](architecture/main-app-target-layout.md), [legacy](architecture/legacy-boundaries.md) |
| Preprocessing entry points/order | `legacy-boundary-review` for historical interfaces, `pyside6-gui-cleanup` for desktop orchestration | [Preprocessing](architecture/preprocessing-contract.md) |
| Removed-electrode or kurtosis calibration | `processing` verification scope | [Removed electrodes](quality/removed-electrode-detection-calibration.md), [kurtosis](quality/kurtosis-screening-calibration.md) |
| Recording loading/memmaps | `project-path-audit` for admission and storage paths | [Loading](architecture/eeg-loading-contract.md) |
| Hardware/montages, pipeline methods | `project-path-audit` for admission, `pyside6-gui-cleanup` for desktop setup | [Roadmap](architecture/hardware-pipeline-studio-roadmap.md), [methods](architecture/pipeline-methods.md) |
| Import a Studio configuration or check recording association | `project-path-audit`; `project-io` scope | [Current handoff and evidence limits](architecture/project-io.md#studio-config-handoff), [paired-fixture plan](exec-plans/active/studio-toolbox-handoff.md) |
| Post-processing/FFT crop/export | `processing` verification scope, `project-path-audit` for export destinations | [Exports](architecture/post-processing-export-contract.md), [crop](architecture/fft-crop-method.md) |
| Manifests, project roots, dialogs/imports | `project-path-audit` | [Project I/O](architecture/project-io.md) |
| Publication figures | `project-path-audit` | [Figure standard](quality/figure-generation.md) |
| Correlation figure templates | `project-path-audit` | [Correlation recipe and runnable example](quality/correlation-figures.md) |
| Stats | `pyside6-gui-cleanup` for GUI changes; focused Stats tests | [Statistics/tools](architecture/statistics-tools.md), scoped `src/Tools/Stats/AGENTS.md` |
| Agent-run FPVS study analysis | [fpvs-analysis](../../.agents/skills/fpvs-analysis/SKILL.md), [group comparisons](../../.agents/skills/fpvs-group-comparisons/SKILL.md), [repeated measures and mixed models](../../.agents/skills/fpvs-repeated-measures/SKILL.md) | [Full-audit export](architecture/post-processing-export-contract.md#full-audit-analysis-ready-workbook), [published examples](../../.agents/skills/fpvs-analysis/references/published-methods.md) |
| Free Harmonic Clustering | `project-path-audit` | [Scoped rules](../../src/Tools/Free_Harmonic_Clustering/AGENTS.md), [architecture](../../src/Tools/Free_Harmonic_Clustering/ARCHITECTURE.md) |
| LORETA Visualizer | `loreta` verification scope, `legacy-boundary-review` for retired interfaces | [Scoped rules](../../src/Tools/LORETA_Visualizer/AGENTS.md), [architecture](../../src/Tools/LORETA_Visualizer/ARCHITECTURE.md) |
| Scalp Maps / Sequence Figure | `pyside6-gui-cleanup` + `project-path-audit` | [Scalp Maps](../../src/Tools/Publication_Maps/AGENTS.md), [Sequence Figure](../../src/Tools/Sequence_Figure/AGENTS.md) |
| Publication tables | `publication-table-export` + `project-path-audit` | [Skill](../../.agents/skills/publication-table-export/SKILL.md) |
| Qt smoke definitions | `pytest-qt-smoke` | [Test selection](quality/test-selection.md); execution is CI-only by default |
| Generated files/caches | `cleanup-generated-files` | [Cleanup](quality/garbage-collection.md), [debt](exec-plans/tech-debt-tracker.md) |
| Explicit browser UI work | `frontend-design` for design, `emil-design-eng` for interaction polish, `web-design-guidelines` for review | Use the web property's owning repository and verification |
| Pressure-testing a plan | `grillme` | Inspect locally answerable questions first; ask one question at a time |

## Plans and verification

Read the [active plan index](exec-plans/README.md) for remaining implementation
or acceptance and the [release ledger](exec-plans/active/v3-release-readiness.md)
for installer evidence. Use the [scope map](quality/test-selection.md#scope-map)
for focused checks and [verification gates](quality/verification-gates.md)
for the precommit command, CI and documentation-only changes.

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
