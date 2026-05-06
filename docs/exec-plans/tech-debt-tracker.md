# Technical Debt Tracker

Use this page for known debt that is not yet an active execution plan.

## Active Debt

- `Legacy_App` retirement is in progress under
  `docs/exec-plans/active/main-app-folder-retirement.md`.
- `PySide6_App` retirement is paused until the Legacy boundary is finalized.
- `scripts/gui_wave3_smoke.py` hung during the first Legacy cleanup slice and
  should be reassessed before it is used as a required gate again.

## Tracking Rules

- Promote debt to `exec-plans/active/` when implementation starts.
- Keep entries short and link to a focused architecture doc or plan when one
  exists.
- Remove entries when the debt is fixed or deliberately accepted.
