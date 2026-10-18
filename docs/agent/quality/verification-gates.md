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
  ad-hoc offscreen Qt scripts; they can freeze or hang indefinitely in
  supported local development environments. PySide6/pytest-qt targets execute
  only in the configured CI Qt job unless the user explicitly approves a safe
  visible GUI environment.
  Local GUI verification uses non-GUI checks plus a documented visible/manual
  smoke path.

## Standard Commands

Use the verification driver instead of composing pytest, Ruff, compile, and
audit commands by hand. It selects `.venv1` when present and otherwise `.venv`,
applies the local Qt guard, and keeps output compact.

```console
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
- Free Harmonic Clustering changes: run `python .agents/scripts/verify.py
  --scope free-harmonic-clustering --tier focused`. Run the project-I/O scope
  as well when canonical dataset discovery or containment behavior changes.
- Publication Maps changes: run `python .agents/scripts/verify.py --scope
  publication-maps --tier focused`.
- Publication figure generation changes: run `python
  .agents/scripts/verify.py --scope figures --tier focused`. Figure renderers
  must use `Main_App.exports.figure_style`, not GUI typography helpers.
- Legacy-boundary changes: run `python .agents/scripts/verify.py --scope
  legacy-boundary --tier focused`; retired `Legacy_App` paths must not be
  recreated and historical cleanup must preserve the processing pipeline.
- LORETA Visualizer changes: run `python
  .agents/scripts/verify.py --scope loreta --tier focused`. The historical
  `Tools.SourceLocalization` package remains retired; rendering changes must not move source calculation into
  `renderer.py`, `fsaverage_mesh.py`, or GUI code.
- Processing pipeline changes: run `python .agents/scripts/verify.py --scope
  processing --tier focused`; verify processing order, output filenames,
  sheets, and formats remain compatible.
- Garbage collection and repo-wide invariants are part of `python
  .agents/scripts/verify.py --scope repo --tier precommit`.

## Documentation-only changes

For local verification of instructions, ownership maps and roadmap updates without runtime changes,
run the repository audit and strict documentation build. Inspect referenced
owners and plan status, check relative links/anchors and run `git diff --check`.
Do not run the scientific suite or private-data diagnostics merely to verify
prose; run affected tests only if the change also modifies executable behavior.
Use the selected repository interpreter for `python -m mkdocs build --strict`.
Existing CI workflows may still run the full source suite on documentation
commits; this local guidance does not change workflow triggers or required checks.

## Future acquisition and Studio qualification

Follow the [roadmap](../architecture/hardware-pipeline-studio-roadmap.md) before
claiming new support. Use generated format/montage fixtures and paired Studio
producer/Toolbox consumer fixtures to prove supported versions, units, event
semantics, identities and round-trip preservation where a round trip is defined.
The target includes a third montage without common-orchestrator rewrites;
current inspection-only extension tests do not satisfy processing acceptance.
Preserve the BioSemi golden baseline and distinguish software checks from
physical acquisition/timing calibration. These future gates do not authorize
an unrequested method change or live hardware run.

## CI Change Detection

The Python workflow lints active Main App/tool code (including Stats), tests,
and agent scripts. Its Windows backend job runs the project-I/O and
`backend-hardening` focused scopes without Qt execution. The Linux job runs
the processing bridge recovery/restart smoke in a separate pytest process
before the full CI Qt suite. Run `python .agents/scripts/verify.py --scope
backend-hardening --tier focused` for targeted persistence/recovery/import and
spectral-read and source-model cache regressions; it supplements the broader
domain scopes. Repo-local temporary test directories use short node hashes to
leave Windows path-length headroom for real export and cache filenames.
An explicit pytest `--basetemp` is honored when a checkout still leaves too
little headroom; select a fresh short temporary directory for that run.

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
