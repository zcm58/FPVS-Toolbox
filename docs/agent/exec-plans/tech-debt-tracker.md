# Technical Debt Tracker

This page tracks unresolved, implementation-ready debt. It is not a list of
permanent guardrails, completed migrations, product ideas, or past verification
runs. Measurements below were refreshed against `main` at `712de154` on
2026-10-18; remeasure an item before promoting it to an active plan. The census
uses tracked `src/**/*.py` files, excluding `src/Standalone_Scripts/**` before
reading files, UTF-8-SIG decoding, physical `splitlines()` counts, and Python AST
exception handlers. Module counts include `__init__.py`.

## Open Debt

### TD-001: High-context production modules

- **Evidence:** 107 of 504 production Python modules exceed 600 lines. The
  largest current hotspots are:
  - `Main_App/gui/settings_panel.py` - 4,862 lines
  - `Main_App/processing/frequency_domain_qc.py` - 4,862 lines
  - `Main_App/gui/preprocessing_qc_workflow.py` - 4,860 lines
  - `Tools/Stats/analysis/dv_policy_group_significant.py` - 4,308 lines
  - `Tools/LORETA_Visualizer/gui.py` - 3,807 lines
  - `Main_App/Performance/process_runner.py` - 3,522 lines
  - `Tools/Free_Harmonic_Clustering/exports.py` - 3,393 lines
  - `Main_App/processing/raw_channel_qc.py` - 2,970 lines
- **Cost:** agents must load broad files to make narrow changes, increasing
  context use and the chance of crossing ownership boundaries.
- **Next slice:** choose one behavior-covered owner and extract named helpers
  behind its existing public API. Favor high-churn orchestration before locked
  scientific algorithms.
- **Done when:** the selected owner has a documented responsibility boundary,
  focused characterization tests, and materially smaller change/context scope
  without changed behavior or exports.

### TD-002: Broad exception boundaries

- **Evidence:** 435 `except Exception` handlers remain across 118 production
  Python files. This counts exact AST `Exception` names, including handlers
  that bind an exception variable; it excludes the separate 16 `BaseException`
  handlers across 11 files. No tuple/qualified `Exception` or bare handlers
  were found in this snapshot. They are concentrated in GUI, processing,
  source-production, and export orchestration.
- **Cost:** unrelated failures are hard to attribute, while silent recovery can
  hide bad state from both users and verification agents.
- **Next slice:** tighten handlers only inside one covered workflow. Preserve
  intentional best-effort behavior, add operation/path context to logs, and
  keep user-facing recovery semantics unchanged.
- **Done when:** the selected workflow catches expected exceptions explicitly,
  any remaining broad boundary is justified and logged, and focused failure
  tests cover its recovery behavior.

### TD-004: Current Main App ownership still uses transitional package names

- **Evidence:** active implementations remain under `Main_App/Shared` (12
  Python modules) and `Main_App/Performance` (3 Python modules), while newer
  purpose-based packages expose the intended public import surfaces.
- **Cost:** agents must distinguish current owners, adapters, and historical
  naming before changing loading, exports, processing, or worker behavior.
- **Next slice:** migrate one responsibility at a time behind its existing
  public adapter, update the module map, and retain compatibility only where an
  active caller proves it is needed.
- **Done when:** each migrated responsibility has one documented owner and no
  active caller depends directly on the transitional path.

### TD-005: Default-tool adapter consolidation

- **Owner:** Main App and I/O maintainers; explicitly deferred beyond v3.0.0.
- **Evidence:** FHC now uses neutral exact-XLSX ingestion, but the v3 ledger
  retains follow-up work for shared ROI/harmonic adapters and the remaining
  selected-column readers. This is consolidation, not an identified release bug.
- **Next slice:** inventory active callers, characterize exact values, column
  order, missing-column/error behavior and performance, then migrate one owner
  behind a public API with a thin compatibility adapter where required.
- **Done when:** the migrated owner has one implementation, no new tool-to-tool
  private dependency, and unchanged numerical/export behavior under those checks.

## Tracking Rules

- Give every new item a stable `TD-###` identifier, evidence, a bounded next
  slice, and an observable completion condition.
- Promote an item to `exec-plans/active/` only when implementation starts.
- Reverify counts before planning; snapshots describe scale, not acceptance
  thresholds.
- Remove an item when fixed or explicitly accepted. Keep permanent safety rules
  in `AGENTS.md` or architecture contracts, and keep product backlog in future
  plans instead of this tracker.
