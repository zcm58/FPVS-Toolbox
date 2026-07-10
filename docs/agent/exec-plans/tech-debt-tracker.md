# Technical Debt Tracker

This page tracks unresolved, implementation-ready debt. It is not a list of
permanent guardrails, completed migrations, product ideas, or past verification
runs. Measurements below were refreshed against the repository on 2026-07-10;
remeasure an item before promoting it to an active plan.

## Open Debt

### TD-001: High-context production modules

- **Evidence:** 38 production Python modules exceed 600 lines (excluding
  `src/Standalone_Scripts/**`). The largest current hotspots are:
  - `Tools/LORETA_Visualizer/gui.py` - 3,220 lines
  - `Tools/Stats/analysis/dv_policy_group_significant.py` - 2,256 lines
  - `Main_App/Performance/process_runner.py` - 1,975 lines
  - `Tools/LORETA_Visualizer/renderer.py` - 1,833 lines
  - `Tools/LORETA_Visualizer/source_producers/l2_mne_hauk_zscore.py` - 1,648 lines
  - `Main_App/gui/settings_panel.py` - 1,623 lines
  - `Main_App/gui/preprocessing_qc_workflow.py` - 1,612 lines
  - `Main_App/gui/processing_workflows.py` - 1,433 lines
- **Cost:** agents must load broad files to make narrow changes, increasing
  context use and the chance of crossing ownership boundaries.
- **Next slice:** choose one behavior-covered owner and extract named helpers
  behind its existing public API. Favor high-churn orchestration before locked
  scientific algorithms.
- **Done when:** the selected owner has a documented responsibility boundary,
  focused characterization tests, and materially smaller change/context scope
  without changed behavior or exports.

### TD-002: Broad exception boundaries

- **Evidence:** 362 `except Exception` handlers remain across 88 production
  Python files (excluding `src/Standalone_Scripts/**`). They are concentrated
  in GUI, processing, source-production, and export orchestration.
- **Cost:** unrelated failures are hard to attribute, while silent recovery can
  hide bad state from both users and verification agents.
- **Next slice:** tighten handlers only inside one covered workflow. Preserve
  intentional best-effort behavior, add operation/path context to logs, and
  keep user-facing recovery semantics unchanged.
- **Done when:** the selected workflow catches expected exceptions explicitly,
  any remaining broad boundary is justified and logged, and focused failure
  tests cover its recovery behavior.

### TD-003: Stats is outside the normal Ruff baseline

- **Evidence:** `pyproject.toml` excludes `src/Tools/Stats` (66 Python files,
  17,540 lines). An explicit Ruff scan currently reports 496 findings: 344
  `F405`, 131 `F401`, 12 `E702`, 6 `F821`, and 3 `E402`. The wildcard-import
  compatibility surface in `Stats/ui/stats_window_support.py` drives most
  undefined/wildcard symbol noise.
- **Cost:** touched Stats files can regress without the repository's normal
  static checks, and real undefined names are buried in compatibility noise.
- **Next slice:** first fix the six `F821` findings with focused tests. Then add
  a touched-file lint ratchet and replace wildcard imports in small UI slices.
- **Done when:** touched Stats files cannot add new Ruff findings and the global
  exclusion can be narrowed or removed without a behavior-changing sweep.

### TD-004: Current Main App ownership still uses transitional package names

- **Evidence:** active implementations remain under `Main_App/Shared` (11
  Python modules) and `Main_App/Performance` (3 Python modules), while newer
  purpose-based packages expose the intended public import surfaces.
- **Cost:** agents must distinguish current owners, adapters, and historical
  naming before changing loading, exports, processing, or worker behavior.
- **Next slice:** migrate one responsibility at a time behind its existing
  public adapter, update the module map, and retain compatibility only where an
  active caller proves it is needed.
- **Done when:** each migrated responsibility has one documented owner and no
  active caller depends directly on the transitional path.

### TD-005: Epoch Averaging beta lives under misleading active package names

- **Evidence:** active imports still target
  `Tools/Average_Preprocessing/New_PySide6` and
  `Tools/Average_Preprocessing/Legacy/advanced_analysis_core.py`.
- **Cost:** the names imply retired code even though the GUI and core are the
  intentionally retained Epoch Averaging beta feature.
- **Next slice:** when explicitly scheduled, rehome the active GUI and
  UI-independent core under purpose-based names with compatibility adapters and
  focused behavior tests. Do not remove or redesign the beta feature as part of
  this debt item.
- **Done when:** normal runtime imports use the new owner, the beta behavior and
  outputs are unchanged, and legacy-named adapters can be removed or clearly
  bounded.

### TD-006: LORETA source rebuilds do not reuse inverse-model work

- **Evidence:** the retained one-click rebuild already generates both default
  source methods, but compatible project inputs/model preparation are still
  repeated and no project-local inverse-model cache with strict signatures is
  present.
- **Cost:** source-map rebuilds repeat expensive scientific setup and make
  iterative validation slower for users and agents.
- **Next slice:** share compatible input/model preparation across the batch
  rebuild and add a project-local cache keyed by method, source space, montage,
  channel set, fsaverage fingerprints, and every numerical option that changes
  the inverse result.
- **Done when:** repeated compatible rebuilds reuse the cached model, any
  signature change invalidates it, and focused producer tests prove that L2-MNE
  and eLORETA numerical semantics remain separate.

## Tracking Rules

- Give every new item a stable `TD-###` identifier, evidence, a bounded next
  slice, and an observable completion condition.
- Promote an item to `exec-plans/active/` only when implementation starts.
- Reverify counts before planning; snapshots describe scale, not acceptance
  thresholds.
- Remove an item when fixed or explicitly accepted. Keep permanent safety rules
  in `AGENTS.md` or architecture contracts, and keep product backlog in future
  plans instead of this tracker.
