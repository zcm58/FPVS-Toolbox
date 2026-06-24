# Technical Debt Tracker

Use this page for known debt that is not yet an active execution plan.

## Active Debt

- `Legacy_App` and `PySide6_App` have been retired. The active guardrail is
  `.agents/scripts/audit/agent_audit.py`; do not restore those package paths.
- Broad exception handling is concentrated in high-risk processing/GUI
  orchestration modules. A read-only scan found many existing `except Exception`
  or silent `pass` patterns in `process_runner.py`, `preprocess.py`,
  `processing_controller.py`, `processing_inputs.py`, `processing_workflows.py`,
  and `post_process.py`. Do not sweep-fix these; tighten them only in focused
  slices with behavior coverage.
- Oversized modules remain in Stats workers/controllers, Plot/Ratio GUI code,
  `Main_App` processing/preprocessing, and diagnostics. Treat these as future
  focused refactors, not opportunistic cleanup during behavior-sensitive work.
- High-context modules are now a maintainability and agent-cost concern. Future
  refactors should reduce file size and cognitive load without changing
  behavior, prioritizing `src/Tools/Publication_Report/analysis_tables.py`,
  `src/Tools/Stats/analysis/dv_policy_group_significant.py`,
  `src/Tools/LORETA_Visualizer/gui.py`,
  `src/Tools/LORETA_Visualizer/source_producers/l2_mne_hauk_zscore.py`,
  `src/Tools/LORETA_Visualizer/renderer.py`, and
  `src/Main_App/Performance/process_runner.py`. Prefer extracting named helper
  modules behind the existing public entry points, then run focused tests for
  the touched behavior.
- `src/Standalone_Scripts/**` is developer-only scratch/manual material. Agents
  should not read it, route work through it, or treat it as user-facing/runtime
  precedent unless the user explicitly asks about that folder.
- Preserve root `.fpvs_cache/` when it contains local MNE/fsaverage template
  data for LORETA Visualizer. Routine cleanup may remove generated artifacts
  such as `site/`, `.codex-tmp/`, test scratch folders, and Python caches, but
  root `.fpvs_cache/` is not a default deletion target.
- LORETA Visualizer source-map build performance is deferred as a non-essential
  follow-up after the beta eLORETA volume branch. Future work should add
  selected-column FullFFT parsing and a project-local inverse-model cache with
  strict method/source-space signatures; see the deferred Phase 6H-A(6) plan.
- Retired `Main_App` package names are now guarded by `.agents/scripts/audit/agent_audit.py`;
  future debt should focus on oversized modules and behavior-covered cleanup,
  not resurrecting historical package wrappers.
- Relevant Publications is intentionally not user-facing. Rebuild it as a
  reviewed user page and app Help entry only after the citation list and scope
  are explicitly specified.

## Latest Garbage-Collection Scan

Run after adding the mechanical garbage-collection gate:

- Passed with `.\.venv1` activated: `python .agents/scripts/audit/agent_audit.py`
- Passed with `.\.venv1` activated: `python .agents/scripts/audit/agent_audit.py --check garbage-collection`
- Passed: tracked artifact scan for cache/build/temp patterns returned no
  matches.
- Debt-marker grep found no repo debt markers outside the audit check itself.
- Compatibility/oversize/broad-exception scans identified the active debt above.

## Tracking Rules

- Promote debt to `exec-plans/active/` when implementation starts.
- Keep entries short and link to a focused architecture doc or plan when one
  exists.
- Remove completed plans when implementation finishes. Do not reference
  completed plans in routine agent routing unless the user explicitly asks for
  historical plan context.
- Remove entries when the debt is fixed or deliberately accepted.
