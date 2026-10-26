# Guided pipeline setup

## Scope

Implement the approved optional guided workflow in Settings > Processing, using
the current versioned methods. Retain direct settings editing. Do not introduce
new algorithms, reorder processing, start processing on Save, or add controls to
the main processing screen.

Seven compact pages cover recording setup, reference/channels, filtering,
resampling, channel QC/repair, epochs/spectra, and review. Existing project values
seed an isolated draft. Back/Next and page navigation never save. Final Save
pipeline validates and atomically updates the current project; Cancel preserves
saved settings and caches. Show current methods as values while only one is
qualified. Future implementations can add method selectors within the same
fixed sections.

Use shared PySide6 components and existing backend validators. Keep pages within
the supported 1280x900 workspace without whole-page scrolling. Hardware changes
retain explicit confirmation and resolved capability limits. Preserve advanced
protocol/marker configurations that are not editable in the initial wizard.

Opening guided setup requires an active idle project and no unsaved Settings
draft; disabled-button guidance explains how to resolve these states. After a
successful save, retire the existing Settings page through its normal completion
path so reopening cannot expose stale controls. Recheck processing state at Save.

## Ownership and work

- [x] Pure project draft, shared validation, review changes and atomic save.
- [x] Seven-page dialog, field applicability, navigation and final review.
- [x] Settings entry, Processing tab name, busy/draft guards and post-save handoff.
- [x] Focused model/static tests and registered CI-only Qt coverage.
- [x] Architecture/user documentation and visible/manual acceptance path.
- [ ] CI Qt execution and visible acceptance on supported desktop environments.

The project draft and dialog remain separate from numerical execution. Saving
must preserve unrelated project data, detect concurrent conflicting changes,
retain current scientific fingerprints for unchanged settings, and report save
failure without mutating the live project.

Scientific edits atomically activate the durable per-recording settings receipt
in `processing.pipeline_settings_freshness`. The processing ledger captures
identity before execution; downstream release requires current receipts for all
active contributions. This prevents Resume or a partial Single run from clearing
the requirement for older outputs. Numerical fingerprints remain unchanged.

## Verification

Run focused GUI/project checks, invariant audits, lint/compilation, and strict
documentation build. No local Qt/offscreen workflows or broad scientific tests.
Visible acceptance: open Settings > Processing > Guided setup on each supported
hardware profile; review unchanged values, navigate back/jump, edit and cancel,
then edit/save/reopen/restart. Confirm invalid inputs and active processing block
saving, advanced marker settings survive, the final review identifies changed
values/reprocessing, and no processing starts automatically.

## Verification record

Local source checks, 2026-10-19, using `.venv/Scripts/python.exe`:

- `.agents/scripts/verify.py --scope pipeline-setup --tier focused`: 117 passed;
  GUI/path audits, changed-file Ruff and compilation passed.
- `.agents/scripts/verify.py --scope gui --tier focused`: 689 passed; GUI-safe
  checks only. Registered Qt files were compiled/linted, not executed.
- `-m pytest -q tests/processing/test_pipeline_settings_freshness.py
  tests/processing/test_processing_ledger.py
  tests/processing/test_processing_full_fft_provenance.py
  tests/processing/test_frequency_domain_qc.py`: 232 passed, 1 platform skip.
  Two subsequent freshness cases passed in the final setup scope above.
- `.agents/scripts/audit/agent_audit.py`,
  `.agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`,
  `-m mkdocs build --strict`, and `git diff --check`: passed.

The `repo --tier precommit` driver completed its audit/lint/compile stages but
was stopped when it launched the unscoped repository test suite. Full-suite
completion is not claimed; this implementation uses the focused checks requested
for the processing work. Numerical implementations were not changed. The new
Qt test file defines 17 cases for CI; visible interaction and final pixel fit
remain unverified locally under the repository's Qt policy.

## Changed-file ownership

- Project draft: `src/Main_App/projects/pipeline_setup.py`;
  `tests/project_io/test_pipeline_setup.py`.
- Dialog and integration: `src/Main_App/gui/pipeline_setup_dialog.py`,
  `pipeline_setup_workflow.py`, `settings_panel.py`,
  `settings_preprocessing_page.py`, `settings_feedback.py`;
  `tests/gui/test_pipeline_setup_dialog_qt.py`,
  `test_pipeline_setup_workflow_static.py`, `test_frontend_settings_qt.py`.
- Freshness: `src/Main_App/processing/pipeline_settings_freshness.py`,
  `processing_ledger.py`, `frequency_domain_qc.py`;
  `tests/processing/test_pipeline_settings_freshness.py`.
- Verification routing: `.agents/verification.toml`, `tests/qt_test_files.txt`.
- Guidance: `AGENTS.md`, `ARCHITECTURE.md`, `docs/agent/agent-index.md`,
  `docs/agent/architecture/gui.md`, `pipeline-methods.md`,
  `hardware-pipeline-studio-roadmap.md`, this plan, `docs/user/index.md`,
  `docs/user/reference/eeg-hardware.md`.

All saved state is rooted in the active `Project.project_root` and
`Project.manifest_path`. No machine-specific runtime paths were added or
removed. Future methods belong in the existing versioned slots; the guided
workflow's page descriptors and backend policy are the extension points for
their qualified controls.
