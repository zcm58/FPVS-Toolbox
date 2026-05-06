# Diagnostics

Diagnostics are split by audience and side effects.

Runtime toolbox diagnostics live under `src/Main_App/diagnostics/`. These modules
observe and report app, run, or project state. `audit.py` owns preprocessing
audit summaries and JSON helpers; `event_time_lock_report.py` owns the event/epoch
time-lock report CLI/GUI helper. They must not mutate EEG data, change
preprocessing order, alter project files, or change export formats.

Repo-evaluation scripts live under `scripts/` and `.agents/skills/*/scripts/`.
These scripts enforce agent, CI, package-layout, GUI, path, and protected-boundary
rules. They are not toolbox runtime APIs.

Manual project/data investigation utilities live under
`scripts/manual_diagnostics/`. These are developer-run scripts for inspecting a
specific local project or dataset. They should take project paths from CLI
arguments or environment variables, not hardcoded local user paths.

Rules:

- Active runtime imports should use `Main_App.diagnostics`.
- `src/Main_App/PySide6_App/diagnostics/event_time_lock_report.py` and
  `src/Main_App/PySide6_App/utils/audit.py` are compatibility wrappers only.
- Keep app/run diagnostics behavior-preserving and read/report oriented.
- Keep repo-quality checks out of runtime packages.
- Keep Stats-specific diagnostics inside `src/Tools/Stats/` unless a Stats
  refactor explicitly scopes a move.
