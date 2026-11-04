# Verification Gates

Start with the narrowest affected scope from
[test selection](test-selection.md#scope-map). Use skill-local audits for
initial diagnosis; do not broadly reread code to reconfirm a passing invariant.

## Command Boundaries

- Bound exploratory/import probes and keep them interruptible. Avoid broad
  GUI/tool import sweeps: optional dependencies may initialize windows,
  processes, or slow scientific libraries. Probe one public surface at a time.
- If a probe hangs or reaches an unrelated optional dependency, stop and report
  the attempted command, first failing module, and safer replacement check.
- Qt execution is CI-only unless the user explicitly approves a safe visible
  environment. Never set `QT_QPA_PLATFORM=offscreen` or run ad-hoc offscreen Qt
  locally. GUI changes need non-GUI checks and a documented visible smoke path.

## Standard Commands

With the available repo environment active
([setup](../guides/development.md)), use the driver rather than assembling
pytest/Ruff/compile/audit bundles by hand:

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

The driver selects `.venv1`, then `.venv`. Focused is the normal change loop;
precommit is the lightweight local handoff: all invariant audits, changed
Python lint/compilation, the chosen scope's bounded tests, and changed non-Qt
tests. `--scope repo` does not run the full application suite or infer feature
coverage, so run the affected focused scope first. Use `--list` to preview
commands and `--check-config` to validate registry changes.

Scope definitions and manual smoke paths live in `.agents/verification.toml`;
Qt dependencies live in `tests/qt_test_files.txt`. Keep these authoritative
rather than copying test lists into docs.

## Targeted Checks

The [scope map](test-selection.md#scope-map) routes all supported features,
including `pipeline-methods` and `pipeline-setup`. Additional obligations:

- Processing/export work preserves order, fingerprints, filenames, sheets, and
  formats under the [processing](../architecture/preprocessing-contract.md)
  and [export](../architecture/post-processing-export-contract.md) contracts.
- Shared harmonic-selection changes need `publication-maps` and `stats`;
  figure-style changes need `figures` plus the affected tool. Renderers use
  `Main_App.exports.figure_style`, not GUI typography.
- Updater changes retain the disposable Windows download/install/relaunch
  [smoke path](../architecture/updater.md); never replace the user's production
  installation as a test.
- Project/path tests use isolated temporary roots. FHC changes that alter
  canonical discovery or containment also need `project-io`.
- LORETA rendering must not absorb source calculations. Retirement cleanup
  must preserve supported processing and compatibility contracts.

## Documentation-only Changes

For instructions, ownership maps, or roadmap edits without runtime changes:

```console
python .agents/scripts/audit/agent_audit.py
python -m mkdocs build --strict
git diff --check
```

Use the repo interpreter. Also verify relative links/anchors, referenced owners,
and plan status against the checked-out tree; MkDocs covers user documentation
and is not a complete agent-doc link checker. Do not run scientific suites or
private-data diagnostics solely for prose. Existing CI triggers remain intact.

## Acquisition and Studio Qualification

Follow the [roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
before extending or claiming support beyond the four implemented routes.
Use generated format/montage fixtures and paired Studio producer/Toolbox
consumer evidence for supported versions, units, events, identity, and defined
round trips. Preserve the BioSemi baseline and distinguish software checks
from laboratory amplitude/timing qualification. These gates do not authorize
a method change, live hardware run, or arbitrary Studio compatibility claim.

## CI Change Detection

[Python CI](../../../.github/workflows/python-package.yml) lints active
application/tool code (including Stats), tests, and agent scripts. Windows runs
`project-io` and `backend-hardening` without Qt. Linux runs isolated
processing-bridge and selected GUI regressions before the full suite, with
Qt enabled only in CI. The full suite excludes opt-in standalone-script tests.

Repo test temporaries use short node hashes for Windows path-length headroom;
an explicit pytest `--basetemp` is honored. Choose a fresh short directory
if a long checkout path still needs more room.

Change-sensitive CI audits need a committed comparison point:
`agent_audit.py --base-ref <revision>` or `FPVS_AGENT_AUDIT_BASE_REF`.
A clean-worktree audit against `HEAD` cannot inspect already-committed changes.

## Reporting Failures

Report the exact command, first relevant error, whether it appears related to
the change, and residual risk. For unexecuted GUI behavior, name the CI target
and visible/manual smoke path; do not substitute local offscreen execution.
