# Verification Gates

Use the narrowest executable gate that can prove the change first, then broaden when the change touches shared behavior. Prefer skill-local scripts over manually reading broad folders.

For a compact command map, use `docs/agent/agent-index.md`.

## Command Boundaries

- Do not run exploratory commands without a bounded timeout. Use short bounds
  for import probes and audits, and stop rather than letting a command run
  indefinitely.
- Avoid broad "import every GUI/tool module" sweeps as verification. GUI imports
  can cascade into optional analysis dependencies, windows, process launchers,
  or slow scientific library initialization.
- Prefer the focused verification scope and narrow subprocess import probes for
  the exact public API being changed. Use direct skill audits only for initial
  diagnosis.
- If an import probe exceeds its expected runtime or reaches an unrelated
  optional dependency failure, stop and report the attempted command, first
  failing module, and safer replacement check.
- Do not combine many high-risk imports into one long process. Probe one import
  surface or one small module group at a time so failures are attributable and
  interruptible.
- Do not run Qt tests locally. Never set `QT_QPA_PLATFORM=offscreen` or launch
  ad-hoc offscreen Qt scripts; they can freeze or hang indefinitely in this
  Windows environment. PySide6/pytest-qt targets execute only in the configured
  CI Qt job unless the user explicitly approves a safe visible GUI environment.
  Local GUI verification uses non-GUI checks plus a documented visible/manual
  smoke path.

## Standard Commands

Use the verification driver instead of composing pytest, Ruff, compile, and
audit commands by hand. It selects `.venv1` when present and otherwise `.venv`,
applies the local Qt guard, and keeps output compact.

```powershell
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Choose the scope from `docs/agent/agent-index.md`. The focused tier is the
normal change loop; the precommit tier is the broad local handoff gate.

## Targeted Checks

- GUI changes: run `python .agents/scripts/verify.py --scope gui --tier
  focused`; document the visible/manual smoke path for behavior that requires a
  window. Qt tests remain CI-only by default.
- Updater changes: run `python .agents/scripts/verify.py --scope updates --tier
  focused`, then document manual Windows smoke for `File > Check for Updates`
  and installer `/RELAUNCH=1`.
- Project path or file I/O changes: run `python .agents/scripts/verify.py
  --scope project-io --tier focused`; tests must use isolated temporary paths.
- Publication Maps changes: run `python .agents/scripts/verify.py --scope
  publication-maps --tier focused`.
- Publication figure generation changes: run `python
  .agents/scripts/verify.py --scope figures --tier focused`. Figure renderers
  must use `Main_App.exports.figure_style`, not GUI typography helpers.
- Legacy-boundary changes: run `python .agents/scripts/verify.py --scope
  legacy-boundary --tier focused`; retired `Legacy_App` paths must not be
  recreated and historical cleanup must preserve the processing pipeline.
- Source Localization/eLORETA or LORETA Visualizer changes: run `python
  .agents/scripts/verify.py --scope loreta --tier focused`. Source Localization
  remains removed; rendering changes must not move source calculation into
  `renderer.py`, `fsaverage_mesh.py`, or GUI code.
- Processing pipeline changes: run `python .agents/scripts/verify.py --scope
  processing --tier focused`; verify processing order, output filenames,
  sheets, and formats remain compatible.
- Garbage collection and repo-wide invariants are part of `python
  .agents/scripts/verify.py --scope repo --tier precommit`.

## CI Change Detection

CI must give change-sensitive audits a committed comparison point with
`agent_audit.py --base-ref <revision>` or `FPVS_AGENT_AUDIT_BASE_REF`. A plain
clean-worktree audit compares against `HEAD` and cannot detect files changed
only in already-created commits.

## Reporting Failures

If a command cannot run, report:

- exact command attempted;
- failure reason or first relevant error;
- whether the failure appears related to the change;
- residual risk.
