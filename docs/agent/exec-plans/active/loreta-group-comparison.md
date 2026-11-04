# Live two-group LORETA comparison

Status: implementation, source verification and scoped visible Windows review
complete, 2026-11-04. User requested simultaneous
interactive group brains. Preceding scientific/rendering changes are preserved.
Qt CI, other-platform graphics and real-project acceptance remain separate.

## Scope and resume

- Read tool rules and this checkpoint table; inspect the current diff before
  resuming. Keep the root task's bounded keep-awake lease in task context only.
- Compare prepared maps for exactly two explicit canonical groups, one canonical
  condition, the same numerical method and exact summary. Never infer identity
  from filenames, display labels or folder names. Missing/ambiguous pairs fail
  visibly; no fallback summary or substituted cohort.
- Display only: no inverse, harmonic selection, source aggregation, group
  contrast or inferential test. Each group's existing mask retains its own
  within-group meaning. Values and outputs remain unchanged.
- Two lazy 3D panes share camera, controls and color limits. Preserve normal
  single-view behavior. MRI and publication exports retain their current flows;
  never export only one brain while implying a paired export.
- Parent owns docs/integration/visible review; `group_comparison.py` owns pure
  identity/pair validation; GUI owns worker orchestration; renderer owns linked
  cameras. Do not add project discovery or source math to the renderer.

## Checkpoints

| ID | State | Acceptance |
| --- | --- | --- |
| G0 | Complete | GUI/protected audits pass; existing metadata and renderer boundaries reviewed. |
| G1 | Complete | Strict pair identity/exact summaries/two groups/configuration compatibility; 63 pure tests passed. |
| G2 | Complete | Lazy second renderer, bidirectional camera, coalesced redraws, aspect-aware framing and cleanup; native-camera regression tests and visible drag/zoom/reset passed. |
| G3 | Complete | Worker-loaded pairs, shared scale/settings, group labels, exact-summary failures; cortical/volume/condition/summary/MRI transitions visibly reviewed. |
| G4 | Complete | Independent review clean; LORETA 681, GUI 721 and repository 646 / 1 skipped passed; strict docs and scoped links passed; visible synthetic review passed. |

## Verification and handoff

Use `.agents/scripts/verify.py --scope loreta --tier focused`, the GUI focused
gate, then `--scope repo --tier precommit`; run strict MkDocs and focused doc
link/owner checks. Keep native Qt tests registered for CI. The user authorized
visible Toolbox inspection; use only cached fsaverage and clearly synthetic
prepared two-group maps for local review, never offscreen Qt or private projects.

Visible acceptance: enable comparison, verify group labels and identical legend
limits, change condition/summary/method, rotate/zoom either pane, change masks and
cutoffs, reset, toggle comparison, resize within 1280x900, and close while loading.
Check missing pairs and MRI transition. Record performed checks separately from
unperformed CI, other-platform graphics and real-project acceptance.

## Evidence

- GUI focused gate: 721 tests passed. GUI owner checks: 89 tests passed,
  including 16 comparison worker/controller cases. Qt smoke added to the
  already registered source-options test module; local execution remains CI-only.
- First focused LORETA run found a pre-existing Windows test timestamp collision:
  both rewritten importer fixtures were 375 bytes and 55/100 immediate rewrites
  retained the same mtime. The test now advances mtime explicitly; all ten
  importer tests pass. Production cache behavior is unchanged.
- Visible review exposed narrow-viewport clipping and VTK camera copying without
  advancing its modification time. Aspect-aware fitting and explicit `Modified()`
  after `DeepCopy()` repair both; tests now check modification time as well as
  camera values. Final visible run confirmed both panes fit, bidirectional camera
  updates, Reset and split-to-combined transitions.
- Synthetic prepared files exercised cortical and volume methods, two conditions,
  mean/median, group counts, shared ranges, missing Group B median, comparison
  exit, maximize/restore and MRI handoff. Missing pairs failed visibly; MRI
  disabled comparison and restored its normal preview/export flow. This used
  the actual tool page with cached fsaverage, no project processing or downloads.
  Per-group masks, stale-worker/close paths, all-condition/fixed scales and
  configuration mismatches also have safe controller/native tests; full native
  Qt CI and private-project qualification are not claimed.

## Changed owners and commands

- Runtime: `src/Tools/LORETA_Visualizer/gui.py`, `renderer.py`, new
  `camera_link.py` and `group_comparison.py`. Processing/source producers and
  retired `Main_App/Legacy_App`, `Main_App/PySide6_App`,
  `Tools/SourceLocalization` paths are untouched by this feature.
- Tests: new `tests/loreta/test_camera_link.py`, `test_group_comparison.py`,
  `test_group_comparison_gui.py`; updated `test_renderer_updates.py`,
  `test_prepared_payload_importer.py` and
  `tests/gui/test_loreta_source_options_qt.py`.
- Docs: tool `AGENTS.md`/`ARCHITECTURE.md`, user LORETA guide, agent validation
  guide, plan index and this checkpoint ledger. Existing earlier edits remain.
- Passed: `verify.py --scope loreta --tier focused`,
  `verify.py --scope gui --tier focused`, `verify.py --scope repo --tier precommit`,
  `python -m mkdocs build --strict`, `git diff --check`; commands use the repo
  `.venv` and `.agents/scripts/verify.py`. Native Qt smoke remains CI-only;
  visible review covered the actual page with synthetic prepared data.
