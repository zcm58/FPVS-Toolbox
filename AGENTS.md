# AGENTS.md

## Repo Purpose

FPVS Toolbox is a PySide6 desktop application for preprocessing, cleaning,
visualizing, and statistically analyzing EEG data from Fast Periodic Visual
Stimulation experiments. Releases currently ship through a Windows installer.

## Working Rules

- Think before coding: state assumptions, surface ambiguity, and ask when the safe interpretation is unclear.
- Prefer the smallest behavior-preserving change that solves the task.
- Touch only files required by the task; do not refactor adjacent code opportunistically.
- Preserve existing processing order, data formats, exports, and user workflows unless the task explicitly changes them.
- Development and source execution may occur on Windows 11 or CachyOS (Arch
  Linux). Keep paths, subprocesses, GUI behavior, and tests compatible with
  both; prefer `pathlib`, Python/PySide6 platform abstractions, and one simple
  shared implementation. Isolate OS-specific behavior only when packaging or
  system integration requires it.
- Prefer executable checks over broad reading. Use the available `.venv1` or
  `.venv` environment, then run the relevant skill audit or
  `python .agents/scripts/audit/agent_audit.py`. Shell-specific setup lives in
  [docs/agent/guides/development.md](docs/agent/guides/development.md).
- Treat [ARCHITECTURE.md](ARCHITECTURE.md) as the repo map before structural changes; do not read every architecture page by default.
- Start with [docs/agent/agent-index.md](docs/agent/agent-index.md) when choosing skills, scripts, and focused tests.
- Treat `src/Standalone_Scripts/**` as an opt-in boundary. Do not list, search,
  read, run, import, edit, or use those scripts as precedent unless the current
  user request explicitly scopes that directory or the user approves access
  after the agent asks. See `src/Standalone_Scripts/AGENTS.md` after access is
  authorized. These scripts are developer-only manual utilities, not active
  runtime or user-facing application behavior.
- For non-trivial refactors, read the active execution plan first. Update architecture docs or the nearest scoped `AGENTS.md` when structure, ownership, boundaries, or workflows change; otherwise state why no doc update was needed.

## Non-Negotiables

- `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` have been retired. Do not recreate them; use purpose-based `Main_App` packages instead.
- Active EEG preprocessing imports should use `src/Main_App/processing/preprocess.py`; this is the current implementation owner.
- Active BDF loading imports should use `src/Main_App/io/load_utils.py`; it delegates to the current shared implementation while the Main App layout is migrated.
- Active Main App GUI imports should use `src/Main_App/gui/`; the main window shell, focused workflow helpers, reusable widgets, style tokens, update manager, and GUI presentation helpers live there.
- New or migrated GUI surfaces should start from `src/Main_App/gui/components/` for shared cards, buttons, forms, status banners, window/dialog shells, action rows, and message helpers before adding local UI primitives.
- Subsection headers should use `Main_App.gui.components.SubsectionHeaderLabel`; edit shared subsection-header font, weight, color, and padding in `src/Main_App/gui/widgets/labels.py`, not per-surface QSS.
- Avoid card-within-card GUI designs unless the user explicitly asks for that visual treatment. `SectionCard` should frame a top-level subsection; tab panes, splitters, setup areas, and other parent layout containers should stay visually flat when they contain section cards.
- New or substantially revised embedded tool pages must fit the supported 1280x900 workspace without a page-level scroll area. When coherent controls cannot fit, divide the workflow into purpose-based tabs or progressive pages instead of adding whole-page scrolling. Content-native scrolling inside tables, text viewers, and focused dialogs remains allowed.
- Publication-oriented figure generation must follow [docs/agent/quality/figure-generation.md](docs/agent/quality/figure-generation.md): matching `.pdf`/`.png` outputs, 600 dpi, Arial figure typography, and figure typography separated from GUI typography.
- Active worker/process-runner imports should use `src/Main_App/workers/`.
- Active project model, project manager, project metadata, projects-root, and preprocessing-settings imports should use `src/Main_App/projects/`.
- Processed-workbook discovery and downstream group identity must use
  `Main_App.projects.dataset_index` through the public `Main_App.projects`
  import surface. Canonical group IDs come from participant metadata in
  `project.json`; tool packages must not infer membership from output folders
  or maintain independent participant/group detection logic.
- Active runtime diagnostics imports should use `src/Main_App/diagnostics/`; repo-evaluation checks belong in `scripts/` or `.agents/skills/`, and manual project probes belong in `scripts/manual_diagnostics/`.
- Source Localization/eLORETA has been removed from active runtime. Do not add GUI, settings, tests, imports, quarantine-tree dependencies, or bundled `fsaverage` MRI template data unless the user explicitly scopes a restoration feature.
- The new LORETA Visualizer work is a separate source-localization visualization branch under `src/Tools/LORETA_Visualizer/`, not a revival of `src/Tools/SourceLocalization/**`. Keep visualizer rendering, mesh helpers, payload adapters, demo data, and tool-local docs in that directory; preserve the boundary where future source-localization calculations produce prepared values and visualizer helpers bridge them into renderer payloads.
- Preserve the ignored root `.fpvs_cache/` when it contains MNE/fsaverage template data for the LORETA Visualizer. It is a local dependency cache, not a deletion target for routine cleanup.
- The active preprocessing order is locked to match the Volfart et al. (2021) FPVS implementation decision: initial reference, drop reference channels, optional channel limit preserving stim, FIR filter, downsample, kurtosis/interpolation, final average reference. Do not reorder filtering and downsampling, change FIR duration scaling, or remove the order/version fingerprint guards unless the user explicitly requests a statistical-method change and updates `docs/agent/architecture/preprocessing-contract.md`, `docs/user/reference/methods-reporting-checklist.md`, and the focused processing-order tests.
- The versioned Stats harmonic-selection profiles are locked statistical
  behavior. New projects explicitly default to
  `dzhelyova_poncet_two_consecutive_failures` v1 with all retained scalp
  electrodes; a missing or unversioned profile in an existing project resolves
  to `legacy_fpvs_toolbox` v1 so prior values do not change silently. The four
  supported profiles are Legacy FPVS Toolbox, Fixed/preregistered domain,
  Significant-only exploratory, and Dzhelyova/Poncet two consecutive failures.
  Adaptive non-legacy profiles average participants within every declared
  group x condition cell, weight groups equally within condition, calculate
  local Z separately by condition, and weight conditions equally; an entirely
  missing declared cell is a hard failure. They use all retained scalp
  electrodes or one frozen a-priori selection mask, never mutable Stats ROIs.
  The literature profile stops only after two consecutive eligible non-base
  harmonics have `z <= 1.64`, includes eligible harmonics through the preceding
  cutoff, and fails if the configured search ceiling is reached first. The
  significant-only profile includes only strict local `z > 1.64` detections in
  its bounded domain. The fixed profile accepts an exact frequency list, upper
  harmonic index, or upper frequency and requires exact BCA columns after
  mandatory dynamic base-overlap exclusion. Legacy alone preserves equal-available-
  workbook pooling, mutable ROI-union scope, fill-through-highest summation,
  and the one-pass greater-than-10 isolated-highest gap guard. Every adaptive
  profile retains the locked neighboring-noise calculation: +/-10 FFT bins,
  excluding target-1, target, and target+1, then dropping one finite minimum
  and maximum before the mean and population SD. Downstream standard consumers
  must use the exact canonical included list and selection fingerprint; they
  must not reselect, refill, or truncate it. Free Harmonic Clustering remains
  independent and consumes original FullFFT plus neutral processing-owned
  provenance, never this standard selected list. Do not alter these contracts
  without an explicitly scoped statistical-method change and corresponding
  architecture, user-method, and focused-test updates.
- Sensitivity Analysis is locked as an input-only idealized design-sensitivity calculator. Its mixed-model mode estimates a minimum standardized detectable contrast conditional on manually entered design assumptions. Do not describe it as observed/post-hoc power or model-fit validation, and do not add project-data reads, observed residuals, fitted variance components, persistence, or Stats-pipeline coupling unless the user explicitly scopes a separate data-informed feature.
- Prefer thin adapters outside protected folders when legacy behavior must be reused.
- Use PySide6 for GUI work. Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports anywhere in repo code.
- Import `QAction` from `PySide6.QtGui` only.
- Do not block the UI thread. Long work must use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly; communicate with signals.
- All project I/O must use the active project root and preserve existing output formats.
- Use structured logging instead of `print` in production code.
- Do not run offscreen Qt workflows in this repo. Do not set
  `QT_QPA_PLATFORM=offscreen`, do not run pytest-qt/offscreen GUI tests, and
  do not launch ad-hoc offscreen Qt scripts; they can freeze or hang
  indefinitely in supported local development environments.
- GUI changes need non-GUI checks plus a documented visible/manual smoke path.
  PySide6/pytest-qt execution is CI-only by default; run it locally only in an
  explicitly user-approved safe visible environment.

## Routing And Verification

- [docs/agent/agent-index.md](docs/agent/agent-index.md) is the compact source
  for skill selection, first commands, focused docs, and verification scopes.
  Run applicable skill-local audits before manual inspection, and do not scan
  broad folders to reconfirm a passing invariant.
- Repo-local skills and rules take precedence over generic installed skills for
  FPVS Toolbox work. Web/frontend skills do not apply to the PySide6 desktop UI
  unless a task explicitly introduces a web surface.
- Use `python .agents/scripts/verify.py --scope <scope> --tier focused` first;
  use `python .agents/scripts/verify.py --scope repo --tier precommit` for the
  broad local handoff gate. The driver selects `.venv1` or `.venv`.
- For GUI changes, leave Qt execution to CI and document the visible/manual
  smoke path. If a gate cannot run, report the command, failure reason, and
  residual risk.
- Use [docs/agent/README.md](docs/agent/README.md) for the knowledge-base map and
  [docs/agent/reviews/pre_ship_checklist.md](docs/agent/reviews/pre_ship_checklist.md)
  for final review criteria.
