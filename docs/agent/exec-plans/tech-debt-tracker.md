# Technical Debt Tracker

Use this page for known debt that is not yet an active execution plan.

## Active Debt

- `Legacy_App` has been retired under
  `docs/agent/exec-plans/completed/main-app-folder-retirement.md`.
- `PySide6_App` has been retired under
  `docs/agent/exec-plans/completed/main-app-folder-retirement.md`.
- `.agents/scripts/smoke/gui_wave3_smoke.py` hung during the first Legacy cleanup slice and
  should be reassessed before it is used as a required gate again.
- Broad exception handling is concentrated in high-risk processing/GUI
  orchestration modules. A read-only scan found many existing `except Exception`
  or silent `pass` patterns in `process_runner.py`, `preprocess.py`,
  `processing_controller.py`, `processing_inputs.py`, `processing_workflows.py`,
  and `post_process.py`. Do not sweep-fix these; tighten them only in focused
  slices with behavior coverage.
- Oversized modules remain in Stats workers/controllers, Plot/Ratio GUI code,
  `Main_App` processing/preprocessing, and diagnostics. Treat these as future
  focused refactors, not opportunistic cleanup during behavior-sensitive work.
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
- Remove entries when the debt is fixed or deliberately accepted.
