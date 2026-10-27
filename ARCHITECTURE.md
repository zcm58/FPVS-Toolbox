# ARCHITECTURE.md

Production recording admission is owned by `Main_App.io.bids_import` and
`bids_loader`, reached from the common full/lazy loader. It publishes verified
project-local BIDS imports and returns MNE Raw. Native BDF/BVCDF samples remain
unchanged; BVRF retains exact calibrated values in a labeled FIF64 derivative.
`io.acquisition_metadata` resolves reference, geometry, channel selection,
event semantics, and qualification into an immutable `io.recording_contract.RecordingContract`
before the shared numerical stages. `processing.pipeline_plan` owns the
lightweight fixed-slot method catalog, persisted selection schema and dispatch.
Scientific implementations remain at their numerical owners; default selections
preserve legacy fingerprints. See [method modules](docs/agent/architecture/pipeline-methods.md).
`io.geometry_metadata` owns acquisition
geometry identities used by provenance, and calibrated spatial-profile metadata
stays upstream. The numerical engine accepts an explicit contract without
resolving a manufacturer. `processing.acquisition_policy` only preserves old
imports; numerical reference operations live in `processing.reference`. See the
[loading contract](docs/agent/architecture/eeg-loading-contract.md) and
[conceptual map](docs/agent/architecture/hardware-pipeline-studio-roadmap.md#intended-conceptual-map-canonical-eeg-recording).

ActiveTwo64, ActiveThree, Brain Products and Unicorn use this shared pipeline.
Project-owned hardware confirmation lives in `projects/hardware.py`; native
format readers, geometry, reference and QC applicability stay in `io/`.
`io.mobile_eeg` admits Unicorn raw BDF/BDF+C using the reviewed unit/grid reader,
retains originals and records any narrow unit-header correction. Its generic
contract prohibits resampling and interpolation. `io.pipeline_events` preserves
canonical sample events through preflight, processing and cache reload. Source
identity and geometry reach exports and cache fingerprints. ActiveTwo64 remains
the locked regression baseline; software tests do not qualify physical hardware
or optional spatial tools. See the
[hardware roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md) and
[format/setup guide](docs/user/reference/eeg-hardware.md) for exact scope.


## Purpose

This file is the top-level map for agents working in FPVS Toolbox. Keep durable architecture details here or in linked docs, not in long prompts.

Use executable checks before broad reading. The compact skill, audit, document,
and test map lives in [docs/agent/agent-index.md](docs/agent/agent-index.md);
shell-specific environment setup lives in
[docs/agent/guides/development.md](docs/agent/guides/development.md). Read a
focused architecture page only when the task touches that area or an audit
reports a relevant issue.

## Execution Plans

Durable refactor and feature plans live under [docs/agent/exec-plans](docs/agent/exec-plans/). Read active plans before changing the areas they cover, then keep the plan's progress, decisions, and verification notes current as work lands. Future plans record approved ideas that are not active work yet; read them only when scoping or starting the matching effort.

Structural refactors must update this file, the relevant focused architecture page, or the nearest scoped `AGENTS.md` in the same PR when they change ownership, module boundaries, workflows, or verification expectations. If no architecture or agent doc changes are needed, record that in the PR handoff or active execution plan.

## Knowledge Base

The docs tree is split into [docs/agent](docs/agent/) for agent-facing guidance and [docs/user](docs/user/) for MkDocs/user documentation. Agent guidance is indexed by [docs/agent/README.md](docs/agent/README.md). Keep root agent guidance compact and move durable agent details into focused docs such as `docs/agent/design-docs/`, `docs/agent/product-specs/`, `docs/agent/references/`, `docs/agent/quality/`, and `docs/agent/exec-plans/`.

## Application Shape

The processing pipeline is the primary product. The intended modular package
lets users select supported processing methods and parameters per project,
producing reproducible, stats-ready outputs across acquisition systems.
FHC, scalp maps, and other analysis/visualization tools are secondary add-ons;
their feature needs should not dictate the core processing architecture or
make running those tools a prerequisite for processing. See the maintainer's
[product direction and reference diagram](docs/agent/architecture/hardware-pipeline-studio-roadmap.md#product-priority-and-maintainer-reference).

Current source ownership and supported behavior are described below. The
[hardware, pipeline, and Studio roadmap](docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
records the intended next architecture: modular acquisition/montages, shared
processing steps selected through persisted project settings and validated
against acquisition capabilities, and complete FPVS Studio
compatibility. Four scoped acquisition routes now reach shared processing;
versioned method slots and persisted selections form the modular foundation.
Settings > Processing offers optional guided setup through a detached project
draft (`projects/pipeline_setup.py`) and a worker-saved dialog
(`gui/pipeline_setup_dialog.py`); `gui/pipeline_setup_workflow.py` owns launch guards.
Alternative methods, their UI selectors and complete Studio handoff remain
future work.
Published installer behavior is bound to its release tag, not later source work.

FPVS Toolbox is a PySide6 desktop application built around GUI entry points,
processing backends, and analysis tools under `src/`. Windows 11 is the current
release platform; source development and execution may also occur on CachyOS
(Arch Linux), so shared runtime code must remain portable between both.

Primary areas:

- `src/Main_App/updates/`: GUI-neutral updater protocol, release metadata,
  verified downloads, cache, and independent installer handoff. The separately
  packaged `src/updater.py` entry point provides Update & Repair without the
  main application or scientific runtime. Keep its contracts aligned with
  FPVS Studio; Toolbox adapters and packaging are documented in
  [docs/agent/architecture/updater.md](docs/agent/architecture/updater.md).
  Public source history, release tags, client updates and downloads use
  `zcm58/FPVS-Toolbox`. The original repository stays private; historical
  release-only assets remain preserved.
- `src/Main_App/gui/`: canonical Main App GUI package. It owns the main-window shell/coordinator, focused GUI workflow helpers, reusable widgets, theme helpers, menu/sidebar/header helpers, icon/style-token/update-manager helpers, and GUI operation guards. `main_window.py` has been appropriately downsized; do not target it for further refactor unless the user explicitly scopes that work.
- `src/Main_App/gui/components/`: canonical shared component layer for new and migrated GUI surfaces. Prefer this import surface for shared cards, buttons, forms, status banners, window/dialog shells, action rows, and message helpers.
- `src/Main_App/exports/`: canonical Main App export package. It owns post-processing/workbook generation and the post-export adapter used by workers and the process runner. It also owns GUI-neutral publication figure and publication-table style contracts used by export tooling. The lightweight style surface must not eagerly import Stats-owned workbook builders; heavy processing exports remain lazy compatibility attributes.
- `src/Main_App/processing/`: canonical Main App processing package. It owns
  active EEG preprocessing, the stable `process_data` entry point,
  processing-controller helpers, neutral ROI settings, project-local neutral FullFFT provenance, and
  per-artifact freshness for derivatives of the accepted harmonic selection.
- `src/Main_App/io/`: canonical Main App I/O import surface. It owns the shared
  exclusive atomic writer (`atomic_write.py`), guarded in-place lock/log opens
  (`safe_file.py`), private process memory-map paths (`memmap_paths.py`),
  exact-column/header reader, separate uncompressed dense-spectral and compact
  condition-table NumPy companions, BDF loading, EEG geometry, file filters,
  resource paths, and legacy XLSX compatibility. `spectral_workbook.py` owns
  reusable workbook sessions and FullSNR window reads; `xlsx_xml.py` owns the
  shared XML cell primitives. Reader-specific ordering and error policies stay
  with their readers.
- `src/Main_App/projects/`: canonical Main App project import surface. It owns
  the project model, project manager workflows, project metadata scanning,
  projects-root helpers, preprocessing-settings normalization, canonical
  group/participant context, and the GUI-neutral processed-workbook dataset
  index used by downstream tools. Generated group folders are validation
  provenance only; canonical participant-group membership comes from
  `project.json`.
- `src/Main_App/workers/`: canonical Main App worker package for Qt workers, the process runner, multiprocessing environment helpers, and the compatibility processing mixin.
- `src/Main_App/diagnostics/`: canonical Main App runtime diagnostics package for preprocessing audit helpers, event-time lock reporting, and runtime log routing. Repo-evaluation scripts stay in `scripts/` and `.agents/skills/`.
- `src/Main_App/settings/`: application settings and settings-path ownership. The package initializer and `settings_paths` remain importable by the standalone updater without project, EEG, or GUI dependencies; `settings_manager` remains excluded from that bundle.
- `src/Main_App/Shared/` and `src/Main_App/Performance/`: same-object compatibility aliases only. Runtime implementations and active imports use purpose-based packages; aliases preserve historical imports, monkeypatches and pickle lookups.
- `src/Main_App/Legacy_App/`: retired historical package. Do not recreate it; active code belongs in purpose-based `Main_App` packages.
- `src/Main_App/PySide6_App/`: retired historical package designation. Do not recreate it; PySide6 runtime code now lives under purpose-based `Main_App` packages.
- `src/Tools/`: embedded GUI tools for preprocessing, plotting,
  statistics, detectability, scalp maps, sequence figures, and the LORETA
  Visualizer. User-facing tool entry points are routed through the Main App GUI.
- `src/Tools/Sequence_Figure/`: embedded publication-figure tool for drawing FPVS stimulus-sequence illustrations from manually selected stimulus images. Its renderer is widget-free and exports PNG/PDF/SVG figures; it is separate from the SNR Plot Generator.
- `src/Tools/Sensitivity_Analysis/`: embedded, input-only idealized design-sensitivity calculator. Its widget-free backends estimate minimum detectable standardized effects for paired/one-sample t-tests, balanced one-way repeated-measures ANOVA, and the supported FPVS random-intercept linear mixed model. Mixed-model sensitivity uses cancellable Monte Carlo simulation in a Qt worker, mirrors the current `condition * ROI` fixed structure, and reports Monte Carlo uncertainty plus fit diagnostics under the simulated assumptions. It is not observed power or model-fit validation and does not read project data, persist settings, write files, or join the Stats pipeline.
- `src/Tools/Free_Harmonic_Clustering/`: clean-room Free Harmonic Clustering
  Analysis tool. Its numerical preparation, inference, and export modules stay
  GUI-neutral; a thin project-bound PySide6 workspace page owns setup, preparation
  review, current-session results, and worker orchestration. It reads original managed
  `FullFFT Amplitude (uV)` condition workbooks through the canonical project
  dataset index, recomputes the paper-specific SNR/z preparation, preserves the
  participant x sensor x harmonic tensor, and runs one paired or independent
  two-level cluster-permutation contrast per planned comparison. New GUI runs
  freeze a versioned analysis-family plan for flat or two-visit projects, with
  paired condition comparisons, group comparisons, visit changes, and group
  differences in visit change. All groups' visit changes share one Holm family;
  legacy one-contrast and repeated-batch APIs remain available unchanged.
  Planned runs use one shared harmonic domain and complete required participant
  cells. New analyses use the fixed 197-edge
  FieldTrip-style clean-room BioSemi64 graph and publish an additive polished
  Excel/run-bundle export. It is separate from locked Standard FPVS Screening
  and does not consume Stats-ready Summed BCA exports or the standard selected
  harmonic list. Both GUI inspection and direct preparation validate the same
  processing-owned FullFFT provenance instead of a Stats cache. See its
  scoped `AGENTS.md` and `ARCHITECTURE.md`.
- `src/Tools/LORETA_Visualizer/`: embedded 3D source-visualization tool. Its
  renderer displays anatomical meshes and prepared source payloads only; the
  current Hauk-informed L2-MNE source-PSD calculation and legacy/exploratory
  workbook-derived producers stay isolated in `source_producers/` and pass
  through tool-local payload adapters. See
  [LORETA Visualizer Architecture](src/Tools/LORETA_Visualizer/ARCHITECTURE.md).
- `src/Standalone_Scripts/`: developer-only scratch/manual scripts. Agents should not read these files, treat them as active architecture, or use them as implementation precedent unless the user explicitly asks about this folder.
- `src/quarantine/`, when present: optional ignored historical quarantine kept
  outside active runtime. Its absence is valid; do not create it to satisfy a
  documentation route.
- `tests/`: unit, integration, and pytest-qt smoke coverage.
- `.agents/scripts/audit/`: repo-level agent invariant checks such as `agent_audit.py`.
- `.github/workflows/docs.yml`: strict user-documentation build and GitHub Pages
  artifact deployment from `main`; no generated documentation branch is needed.
- `.agents/scripts/smoke/`, when present: optional agent-facing probes that are
  not default gates. Its absence is valid.
- `scripts/migration/`: one-off or repeatable local data migration helpers.
- `scripts/debug/`: focused debugging probes.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities. These are not runtime toolbox APIs.
- `scripts/packaging/`: release packaging definitions and installer/build inputs.
- `docs/agent/`: agent-facing architecture, execution plans, quality gates, prompts, and implementation guidance.
- `docs/user/`: user-facing MkDocs source for study workflow, statistics, tools, and reference pages.

Focused architecture pages:

- [GUI](docs/agent/architecture/gui.md)
- [Diagnostics](docs/agent/architecture/diagnostics.md)
- [Main App Target Layout](docs/agent/architecture/main-app-target-layout.md)
- [Project I/O](docs/agent/architecture/project-io.md)
- [Legacy Boundaries](docs/agent/architecture/legacy-boundaries.md)
- [Workers And Threading](docs/agent/architecture/workers-threading.md)
- [Statistics And Tools](docs/agent/architecture/statistics-tools.md)
- [FFT Crop Method](docs/agent/architecture/fft-crop-method.md)
- [Preprocessing Contract](docs/agent/architecture/preprocessing-contract.md)
- [Post-Processing Export Contract](docs/agent/architecture/post-processing-export-contract.md)
- [Processing Mixin Contract](docs/agent/architecture/processing-mixin-contract.md)
- [BDF Loading Contract](docs/agent/architecture/eeg-loading-contract.md)
- [Hardware, Processing, and Studio Direction](docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
- [Module Map](docs/agent/architecture/module-map.md)
- [Protected Paths](docs/agent/architecture/protected-paths.txt)
- [LORETA Visualizer Tool Architecture](src/Tools/LORETA_Visualizer/ARCHITECTURE.md)

## Boundaries

- Prefer one portable implementation for Windows 11 and CachyOS. Use
  `pathlib`, Qt, and standard-library platform abstractions; confine unavoidable
  OS-specific behavior to packaging or focused system-integration adapters.
- GUI code should orchestrate widgets, signals, and user feedback; processing logic belongs in backend, worker, or tool modules.
- `Main_App.processing.harmonic_settings` and
  `Main_App.processing.canonical_harmonics` own the shared versioned harmonic
  settings and accepted-selection contract. The former Stats modules remain
  compatibility exports. Processing, Stats, and LORETA Visualizer package entry
  points load heavy execution/GUI exports lazily so backend contracts can be
  imported without Qt.
- Long-running EEG, plotting, export, and statistics work must run outside the UI thread.
- Historical legacy behavior should be consumed through existing current-app APIs or thin adapters in purpose-based packages. Do not add new `Legacy_App` or `PySide6_App` modules.
- Project-aware workflows should resolve files through the active project root and preserve existing generated formats.
- The historical Source Localization/eLORETA package has been removed from active runtime. Keep `src/Tools/SourceLocalization/**` empty of source files and do not add GUI, settings, tests, or quarantine-tree imports for it unless restoration is explicitly scoped as a new feature. The separate `src/Tools/LORETA_Visualizer/` tool keeps renderer logic separate from its existing `source_producers/` calculations and must not bundle `fsaverage` MRI template data in active source or quarantine.
- The ignored repository-root `.fpvs_cache/` is the local MNE/fsaverage cache used by the LORETA Visualizer. Preserve it during routine cleanup unless the user explicitly requests cache removal.

## Verification Strategy

Use focused checks for the changed area first.

- Skill-driven checks: run the matching `.agents/skills/*/scripts/*.py` wrapper before manual grep or broad document reading.
- GUI wiring or layout changes: pytest-qt smoke test for the changed widget or a documented manual smoke path.
- Processing or export changes: targeted unit tests around data format, processing order, and output paths.
- Retired-path work: activate the available repo environment, then confirm `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` are not recreated with `git diff --name-only` and `python .agents/scripts/audit/agent_audit.py`.
- Agent invariants: activate the available repo environment, then run `python .agents/scripts/audit/agent_audit.py`.
- Local handoff: run `python .agents/scripts/verify.py --scope repo
  --tier precommit` after the relevant focused scopes. It runs the full
  invariant audit, changed Python lint/compile checks, bounded scope tests,
  and changed non-Qt test files. The full suite, including Qt coverage, remains
  in CI.

See [docs/agent/quality/verification-gates.md](docs/agent/quality/verification-gates.md) for the current command list and fallback reporting rules.
