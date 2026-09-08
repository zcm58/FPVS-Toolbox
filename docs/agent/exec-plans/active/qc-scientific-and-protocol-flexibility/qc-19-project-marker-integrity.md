# QC-19: Project Marker Identity and Occurrence Review

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-02, and QC-11
through QC-13. QC-06 is its downstream span consumer, not a prerequisite.

**Status:** implemented on 2026-09-04. Marker identity is project-owned;
unexplained marker loss cannot be treated as proof that stimulation remained
continuous. Current GUI decisions are bound to the reviewed marker-plan and
occurrence fingerprints and record exact scope, reason, UTC review time, and
truthful reviewer-identity status.

Presentation follow-up, 2026-09-08: the user's marker-review screenshot buried
the decision beneath complete interval/sample dumps. A dedicated embedded panel
now leads with canonical recording context, the actual finding, required
duration and three explained choices. Unavailable choices are disabled with
visible reasons; exact evidence remains available in a read-only details dialog.
**Keep planned window** replaces the misleading **Retain Full Occurrence**
label while retaining its existing decision identifier, proposed bounds and
independent-evidence requirement. The window picker leads with seconds and
retains exact sample bounds in its data/tooltips. No marker policy, timing
threshold, crop, evidence requirement, rescan, output or decision receipt changes.
The GUI architecture and user QC guide document the new presentation and
visible smoke; numerical method documents do not need changes.

Validation: `verify.py --scope gui --tier focused` passed 463 locally safe
tests. The focused marker-integrity, summary/decision and lifecycle bundle
passed 62 tests. Changed-file Ruff, compilation, verification configuration
and diff checks passed. Ten new Qt cases are registered in
`tests/gui/test_marker_occurrence_panel_qt.py` for default content, unavailable
choices, action signals, details without a decision, and 1280x900 fit. Qt was
not run locally, per the repo rule. The documented visible smoke remains for CI
or an approved visible session. `verify.py --scope repo --tier precommit`
stopped at the same eight pre-existing path findings under unrelated untracked
`outputs/`; those files were preserved and that full gate is not green.

## Accepted Behavior

1. Add one project-wide **Oddball marker code** to protocol settings. Default
   to integer `55`. FPVS Studio import populates it from `project.json`; manual
   projects enter or accept it once at project level. Require a positive integer
   distinct from every condition-onset code. No per-condition marker code is
   supported.
2. Remove active `50 + condition` inference. Preflight and processing consume
   the same saved code and never switch codes from the observed event stream.
   Use brief GUI text: **“Oddball marker code: Event code emitted for each
   oddball in every condition. Default: 55.”** A recording without enough
   occurrences of that code gets an explicit marker-integrity status rather
   than an inferred substitute.
3. Normalize only repeated occurrences of the same oddball code at the exact
   same sample within one condition occurrence. Keep one deterministic row and
   report the original count, retained count, sample, and number collapsed.
   This normalization alone does not pause processing. Do not silently drop a
   non-simultaneous marker: every early, late, off-phase, or otherwise extra
   event remains visible evidence.
4. Compute expected spacing from QC-12's canonical project oddball rate and the
   actual sample rate. Remove literal 1.2-Hz arithmetic. Record each adjacent
   interval in samples, seconds, and oddball-cycle units; identify missing
   expected markers, extra markers, and phase residuals with a versioned timing
   rule. Provisionally flag a non-simultaneous interval below 0.5 cycle as an
   early/extra marker without deleting it, and an interval above 1.5 cycles as
   a missing-marker gap; equality does not cross either boundary. Estimate
   missing count as `max(1, round(interval_cycles) - 1)` while displaying the
   unrounded interval and phase residual. Version and label the 0.5/1.5 values
   as provisional. Preserve raw events unchanged. Normalized and expected
   positions are derived QC evidence, never fabricated source events.
5. A missing marker or unexplained gap pauses only the affected recording,
   condition, and occurrence before processing. Show the marker code, expected
   rate/cycles, event samples/times, inferred missing-cycle count, phase
   residual, proposed crop, and nearby extra markers in the GUI. Other valid
   occurrences remain independently eligible.
6. Offer **Retain full occurrence**, **Use verified contiguous span**, and
   **Exclude occurrence**. Full retention requires recorded evidence that only
   the trigger was lost and the delivered stimulus remained continuous and
   phase-correct, including an evidence type and note or log reference. A
   contiguous span is eligible only when its observed sequence is unambiguous
   and its exact cycle count and on-bin length satisfy QC-13. Otherwise exclude
   the occurrence. Never bridge a gap merely because the first and last markers
   yield an on-bin FFT length.
7. Use the approved span as the single input to QC-06 and normal processing.
   The runner must not infer marker identity again, normalize differently, or
   rebuild crop bounds. QC-02 reports the raw evidence, normalization, review
   decision/evidence, and final analyzed span. An unresolved occurrence remains
   paused and is never described as retained or passed.

## Owners, Migration, and Provenance

Primary owners are project protocol settings/migration, Studio project import,
`gui/settings_panel.py`, `Shared/fft_crop_utils.py`,
`processing/preflight_qc_plan.py`, `processing/preflight_qc.py`,
`gui/preprocessing_qc_workflow.py`, `Performance/process_runner.py`,
`processing/preflight_qc_cache.py`, processing-ledger/freshness owners, and the
QC-02 report.

For an existing project with no field, first inspect trustworthy project/run
provenance and event evidence. If they consistently establish code 55, propose
55 with source `legacy_evidence_55` and require one explicit confirmation
before the next processing run. If evidence establishes a different single
code, propose that code with its evidence and require confirmation. If evidence
is absent or ambiguous, prefill the recommended default 55 but require entry or
confirmation; record `legacy_default_55` only after that choice. Preserve
historical outputs and their old method identity, but invalidate inferred
crop/preflight caches for a new run; legacy `50 + condition` choices cannot
silently carry forward. If an old dataset used condition-specific oddball
codes, show it as unsupported by the one-code contract and require source
correction or a separately approved future schema. Changing the code
invalidates affected QC, crops, processing caches, and dependent outputs.

Fingerprint the marker-policy version, saved code and source, canonical oddball
rate and expected cycles, raw event digest/source, occurrence bounds, raw and
exact-duplicate-normalized events, interval/phase findings, sample rate,
candidate spans, GUI decision and evidence reference, approved bounds, and
QC-13 fingerprint.

## Verification and Scientific Boundary

Cover default/manual/Studio round-trip, conflicts with condition-onset codes,
proof that codes 51-54 never trigger inference, exact-same-sample normalization
with reporting, preservation of every non-simultaneous extra marker, arbitrary
project and sampling rates, single- and multi-cycle gaps, occurrence-local
pause, all three GUI decisions, evidence-required full retention,
QC-13-qualified contiguous spans, runner reuse of exact approved bounds, cache
invalidation, legacy migration, and report completeness. Prove raw events are
never fabricated and no unresolved gap is crossed. Use non-GUI checks, CI-only
Qt coverage, and a documented visible smoke path.

The implementation updates the project protocol/import, FFT-crop,
preprocessing and processing-ledger, GUI/QC, and methods-reporting
documentation.

Markers can establish the recorded event code and timing, but a missing marker
alone cannot establish whether the visual stimulus continued. FPVS depends on
phase-locked periodic stimulation, and physical timing may require presentation
logs or a photodiode rather than software triggers alone
([Norcia et al., 2015](https://doi.org/10.1167/15.6.4),
[FreqTag](https://doi.org/10.1016/j.dcn.2022.101066),
[BioSemi trigger guidance](https://www.biosemi.com/faq/trigger_signals.htm),
[COBIDAS-MEEG](https://doi.org/10.1038/s41593-020-00709-0)).
