# Diagnostics

Diagnostics are split by audience and side effects.

Runtime toolbox diagnostics live under `src/Main_App/diagnostics/`. These modules
observe and report app, run, or project state. `audit.py` owns preprocessing
audit summaries and JSON helpers; `event_time_lock_report.py` owns the event/epoch
time-lock report CLI/GUI helper; `log_router.py` owns runtime logging routes for
IDE/console output, GUI log-line formatting, and parent-process replay of
worker timing records. They must not mutate EEG data, change preprocessing
order, alter project files, or change export formats.

Repo-evaluation scripts live under `scripts/` and `.agents/skills/*/scripts/`.
These scripts enforce agent, CI, package-layout, GUI, path, and protected-boundary
rules. They are not toolbox runtime APIs.

Manual project/data investigation utilities live under
`scripts/manual_diagnostics/`. These are developer-run scripts for inspecting a
specific local project or dataset. They should take project paths from CLI
arguments or environment variables, not hardcoded local user paths.

Rules:

- Active runtime imports should use `Main_App.diagnostics`.
- Logging policy changes should go through `Main_App.diagnostics.log_router`
  instead of adding new ad hoc `logger.info`/GUI text-log routing helpers.
- Keep app/run diagnostics behavior-preserving and read/report oriented.
- Keep repo-quality checks out of runtime packages.
- Keep Stats-specific diagnostics inside `src/Tools/Stats/` unless a Stats
  refactor explicitly scopes a move.

## Automatic error and crash reporting (planned)

The [shared OpenFPVS reporting contract](https://github.com/zcm58/FPVS-Studio-2.0/blob/master/docs/BUG_REPORTING.md#platform-automatic-error-and-crash-reporting)
defines the payload, delivery limits, privacy controls and acceptance checks.
Toolbox's current runtime logging and installer smoke diagnostics are local.

- Capture unexpected internal faults that interrupt an action at the desktop or
  worker boundary. Recover qualifying native crashes or unexplained unclean
  exits on next launch. Exclude expected validation failures, routine warnings,
  ordinary recording rejections and user cancellations. Correlate an internal
  fault followed by a fatal crash to one incident. Keep the existing workflow's
  progress, failure handling and recovery behavior.
- Use a Toolbox-specific preference in Settings > Diagnostics. Default to
  enabled for fresh installations and preserve saved opt-outs. Apply the
  preference before capture, grant issuance or replay. Disclose the report
  contents before capture. When reporting is turned off, discard unsent reports
  and queue revocation of the scoped grant. Start collecting at activation and
  exclude prior sessions and logs from backfill.
- Capture Toolbox's running version and the OS family and full reported version.
  Include the app build, non-unique hardware model, CPU architecture and model,
  visible GPU models, total RAM, and relevant dependency versions when available.
  Use bounded OS queries. Report a brief redacted category and summary with an
  allowlisted stack excerpt when available. Exclude full logs, absolute paths,
  host and unique hardware identifiers, environment dumps, credentials, user and
  study information, and EEG files or data.
- Persist bounded, redacted pending reports in app-owned storage and retry in
  the background with a scoped installation grant and a durable receipt. The
  dedicated FPVS-Studio-Feedback service owns intake, private issue creation and
  the short maintainer email. The website owns documentation and routing.
  Automatic submission requires no browser interaction. Manual feedback and
  explicit **Share study results…** remain separate workflows.

Verify the target with synthetic desktop and worker faults, a native failure
and next-launch recovery, an outage and replay, and repeated and disabled
cases. Verify that replay reuses the private issue and that confirmed email
delivery sends one notification. Check report contents, startup, GUI
responsiveness and processing recovery on the supported Toolbox targets.
