# Shared Studio–Toolbox handoff

Status: Active — source implementation complete; visible/installed acceptance pending.

Authorized 2026-11-10.

## Outcome and boundary

Both applications use one stable `.fpvsconfig` handoff format for setup and
completed-session exports. Application release versions remain provenance;
optional authoring features do not select another envelope revision. Historical
configs remain readable through explicit adapters. Unknown scientific meaning
must fail with an actionable compatibility error.

This work preserves internal project, acquisition-evidence, RunSpec, SessionPlan,
processing-method and fingerprint contracts. It does not change numerical
processing, infer participant/recording associations, package raw EEG, or qualify
hardware and physical timing.

## Implementation

- [x] Agree the shared format marker, integer revision, document kind, producer
  provenance and optional descriptive-metadata boundary in both repositories.
- [x] Have Studio emit one current format and normalize historical configs into
  its canonical model without per-feature envelope branching.
- [x] Have Toolbox accept the same format and historical configs, validate its
  supported scientific subset, and retain completed-session provenance and
  removed-electrode declarations without guessing canonical raw identities.
- [x] Exercise actual Studio producer fixtures through both applications,
  including completed sessions, historical files, malformed input, unsupported
  scientific semantics and optional metadata.
- [x] Update the canonical contracts and user import guidance.

## Verification and acceptance

Source verification on 2026-11-10: Toolbox project-I/O focused checks passed
1,319 tests with 14 skips and six existing synthetic BIDS warnings; GUI-focused
non-Qt checks passed 774 tests. Toolbox precommit passed 340 tests with two skips,
all audits, changed-file Ruff and compilation. Independent review found no
actionable defects. Four paired fixture copies are byte-identical across the two
repositories. Both strict MkDocs builds and changed-document relative-link checks
passed. Studio's final project-I/O focused gate passed 868 tests with three skips;
its precommit passed 5,931 tests with 33 skips, including Ruff/compilation,
Windows/Darwin mypy and GC/docs hygiene. Studio's docs-focused gate passed 13 tests.
No local Qt execution was authorized.
After deterministic fixture regeneration, the final consumer import/workflow
checks passed 92 tests with one skip; all four fixture copies remained byte-identical.

Visible acceptance remains separate: export setup and a completed synthetic
session from Studio, import each through Toolbox's New Project flow, select the
hardware and raw folder, and inspect protocol/provenance before processing.
Cancel recording-folder selection and verify the project still requires explicit
raw registration. Unsupported designs must fail before a usable project is saved.

Canonical behavior belongs in [Project I/O](../../architecture/project-io.md);
the [roadmap](../../architecture/hardware-pipeline-studio-roadmap.md) retains the
broader integration and hardware qualification boundaries.
