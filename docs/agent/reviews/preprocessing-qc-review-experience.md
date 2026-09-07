# Preprocessing QC review experience: implementation review

Branch: `codex/preprocessing-qc-v3`. Implements the five preprocessing review
recommendations approved on 2026-09-07. Post-processing frequency QC is outside
scope; the shared interpolation-burden review can display confirmed repair
support without changing its decisions.

## Boundaries

Preserve numerical preprocessing order, exact analyzed intervals, reference
settings, kurtosis scores/thresholds, existing automatic policies, geometry,
exports and decision fingerprints. New diagnostics are versioned, provisional,
review-only shadow evidence; they do not enter the approved corroborator
registry or authorize interpolation/exclusion. No representative labeled EEG
calibration dataset is available in this task. Synthetic checks establish
implementation behavior, not empirical accuracy.

## Deliverables

- [x] Peak-preserving overview and bounded background signal inspection with
  true time coordinates, occurrence boundaries and neighboring channels.
- [x] Cross-detector episode navigation, explicit decision consequences,
  selected-undecided actions and reversible bulk edits.
- [x] Configured-reference comparison and localized flatline, candidate
  clipping and jump diagnostics on unfiltered source samples.
- [x] Duration/spatial shadow evidence with explicit assessed scope and no
  automatic authority, plus calibration guidance.
- [x] Proposed/confirmed repair maps and donor support; optional held-out
  spatial prediction is descriptive, never proof of repaired signal accuracy.

## Verification

Registered non-Qt processing/GUI tests cover detector parity, reference and
time coordinates, grouping, decision scope, donor eligibility, source/cache
integrity, cancellation and unchanged numerical authority. CI-only Qt smoke
coverage is registered; no local Qt execution is permitted by the repository.

Commands used the checkout's `.venv/Scripts/python.exe`:

- `python .agents/scripts/verify.py --scope processing --tier focused`:
  1,582 passed, 5 skipped; protected/source-localization audits, Ruff and
  compilation passed. Existing short synthetic FIR/stim warnings remain.
- `python .agents/scripts/verify.py --scope gui --tier focused`:
  375 passed; GUI audit, Ruff and compilation passed. The final leaf-selection
  change also passed Ruff/compilation and has a CI-only signal regression.
- `python -m pytest tests/processing/test_qc_signal_view.py tests/processing/test_kurtosis_review_scan.py -q`:
  49 passed after the final before/after content checks and unavailable-status
  fixes. These overlap the processing suite; do not add them as unique tests.
- `python .agents/scripts/verify.py --scope repo --tier precommit`:
  blocked by the eight unrelated path findings described below, before its
  full repository test run. `git diff --check` passed.

The repo precommit gate stops at eight pre-existing machine paths in user-owned
untracked `outputs/`. Those files are unchanged and excluded from this commit.
All other audit checks passed. No hard-coded production paths were introduced
or removed; viewer project scope comes from `host.currentProject.project_root`.
Prepared checkpoints stay under that root and source requests retain the
project's selected recording path. Existing cleanup owns checkpoint/prefetch
lifetimes; the new viewer keeps only bounded dialog-local summaries.

Visible smoke (not executed locally): run a small project through guided steps 2–7, open kurtosis
signal inspection, compare raw/reference/prepared modes and occurrence
boundaries, inspect a localized event and linked episode, apply selected
pending decisions and undo, review donor locations, cancel an active read,
then complete QC. Confirm unchanged choices remain unchanged and unavailable
diagnostics never imply a clean recording or authorize a repair.

## Review findings resolved

- Reuse MNE public amplitude annotations and interpolation on bounded scratch
  samples instead of copying either numerical algorithm. No new dependency.
- Display cues even when the original preflight and kurtosis results are clear;
  show failed assessments and truncated event lists explicitly.
- Retain peak extrema and exact source/prepared time grids; open short cues
  with surrounding occurrence context, without crossing occurrence gaps.
- Compare actual source/checkpoint content before and after viewing; reject
  same-size restored-timestamp edits. Reuse only already validated source
  digests with their exclusive Raw ownership. Cache keys and numerical
  fingerprints are unchanged.
- Current choices supersede old receipts for proposed donor support;
  directly confirmed unusable sensors remain excluded.

## Exact files changed

Runtime:

- `src/Main_App/gui/interpolation_burden_review_dialog.py`
- `src/Main_App/gui/kurtosis_review_dialog.py`
- `src/Main_App/gui/preprocessing_qc_workflow.py`
- `src/Main_App/gui/qc_repair_support.py`
- `src/Main_App/gui/qc_signal_viewer.py`
- `src/Main_App/gui/signal_review_model.py`
- `src/Main_App/gui/signal_review_panel.py`
- `src/Main_App/processing/interpolation_burden_review.py`
- `src/Main_App/processing/kurtosis_review_scan.py`
- `src/Main_App/processing/prepared_kurtosis_cache.py`
- `src/Main_App/processing/preprocess.py`
- `src/Main_App/processing/qc_review_diagnostics.py`
- `src/Main_App/processing/qc_review_episodes.py`
- `src/Main_App/processing/qc_signal_view.py`
- `src/Main_App/processing/qc_source_prefetch.py`
- `src/Main_App/workers/qc_signal_view_worker.py`

Verification:

- `.agents/verification.toml`
- `tests/gui/test_kurtosis_review_actions_qt.py`
- `tests/gui/test_kurtosis_review_actions_static.py`
- `tests/gui/test_kurtosis_review_dialog_static.py`
- `tests/gui/test_preprocessing_signal_review_static.py`
- `tests/gui/test_qc_signal_viewer_qt.py`
- `tests/gui/test_qc_source_prefetch_static.py`
- `tests/gui/test_signal_review_model.py`
- `tests/gui/test_signal_review_panel_qt.py`
- `tests/processing/test_interpolation_burden_review.py`
- `tests/processing/test_kurtosis_review_scan.py`
- `tests/processing/test_prepared_kurtosis_cache.py`
- `tests/processing/test_preprocessing_qc_workflow_helpers.py`
- `tests/processing/test_qc_review_diagnostics.py`
- `tests/processing/test_qc_review_episodes.py`
- `tests/processing/test_qc_signal_view.py`
- `tests/processing/test_qc_source_prefetch.py`
- `tests/qt_test_files.txt`

Documentation:

- `docs/agent/architecture/preprocessing-contract.md`
- `docs/agent/quality/kurtosis-screening-calibration.md`
- `docs/agent/reviews/preprocessing-qc-review-experience.md`
- `docs/user/reference/index.md`
- `docs/user/reference/preprocessing-qc-review.md`
