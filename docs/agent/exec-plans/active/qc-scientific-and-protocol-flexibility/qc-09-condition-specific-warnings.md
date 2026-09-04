# QC-09: Clear Condition-Specific Electrode Warnings

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** implemented on 2026-09-04 in structured preflight evidence and the
ordinary review table. CI/visible GUI smoke remains at integrated handoff.

### Implementation Progress

- Every enabled-detector full-occurrence finding records electrode, canonical
  condition label, occurrence, analyzed sample bounds, category, evaluated
  denominator, and a concise scope statement. The text distinguishes one-only,
  partial, same-category persistent, and all-flagged/reason-varied cases.
- A reason counts as persistent when at least one category recurs in every
  evaluated occurrence, even if an additional category appears in only one.
- Marker occurrences unavailable to QC are recorded as `Not evaluated` with a
  reason and excluded from the evaluated denominator. Detector Off is also
  presented as `Not evaluated` and cannot leak inferred detector findings.
- Transient rows remain separate, retain their overlapping window identities,
  and have review-only authority. Recording-wide interpolation suggestions
  remain limited to low variance in the same category across every evaluated
  occurrence, plus independently configured manual targets.

### Accepted Behavior and User-Facing Meaning

1. Derive a review finding for every full-condition occurrence classification
   produced by an enabled detector. Keep persistent low variance in every
   evaluated occurrence as QC-04's separate recording-wide proposed
   interpolation. Persistent high-amplitude and rare-burst categories remain
   visible, unselected evidence rather than repair proposals. By itself, an
   occurrence finding cannot trigger automatic
   electrode, condition, recording, or participant exclusion or whole-recording
   interpolation. QC-16 alone governs whether separately validated,
   scope-matched corroboration can authorize interpolation.
2. Display a prominent condition-scope statement in the ordinary preflight
   review rather than only in an expanded payload or tooltip. Lead with the
   electrode, condition label, and occurrence/repetition. State "only" when
   exactly one evaluated occurrence was flagged, and state the comparison count.
   Example: "P7 was flagged as potentially bad in Condition A, occurrence 1
   only. It was not flagged in the other 3 evaluated occurrences."
3. Distinguish these cases explicitly:
   - A1 flagged and A2 unflagged: occurrence-specific, not all of Condition A.
   - One occurrence unscanned/unavailable: show Not evaluated and its reason;
     exclude it from the evaluated denominator and never call it unflagged.
   - All evaluated occurrences flagged in the same category: retain the
     persistent candidate classification and state the full evaluated scope.
   - All evaluated occurrences flagged but categories differ: state that every
     evaluated occurrence was flagged and that the reason varied; do not falsely
     call it a same-category persistent candidate.
   - Experimental detector disabled: show that the applicable experimental
     assessment was not performed, without exposing inferred findings from it
     or calling the recording clean.
4. Show category, measured values, analyzed sample/time span, and short-window
   identity where relevant in expandable details. Explain briefly that these
   flags describe statistics over each analyzed occurrence and do not establish
   continuous impairment or artifact-free unflagged data. Keep transient-window
   results separate from full-occurrence findings.
5. Use canonical project condition and recording identities. Support arbitrary
   condition labels, occurrence counts, presentation/oddball rates, and analyzed
   durations. Bind the evaluated comparison scope to QC-06's exact analysis-span
   provenance so a changed protocol cannot silently reuse old scope wording.

### Implementation Owners, Persistence, and Validation

Keep classification and structured evidence in `raw_channel_qc.py`. Add a
derived occurrence-review collection while preserving the existing persistent
properties and `channels_to_interpolate`. Correct the top-level "passed"
summary and review rules so an occurrence finding makes the result visible.
Carry the structured fields through `preflight_qc.py` and its project-local
cache, then render concise rows through the existing
`gui/preprocessing_qc_workflow.py` review surface. Reuse Main App GUI components,
theme tokens, and existing expandable-detail patterns; do not add page-level
scrolling or card nesting. Include the evidence in QC-02's preprocessing report
and preserve the original detector output separately from any later user
decision.

Version the preflight payload/cache meaning so a cached historic "passed"
result cannot hide occurrence findings. This presentation/review change alone
does not alter EEG processing or justify an independent processing-fingerprint
change; coordinate cache/provenance work with QC-06 and QC-08. Preserve cancel,
failure, and worker-signal behavior; do not inspect or update widgets from the
worker.

Cover A1 flagged/A2 unflagged/B unflagged; unavailable occurrence; every
occurrence flagged with varying categories; same-category persistent findings;
one-occurrence recordings; transient-only findings; detector Off; canonical
condition labels; differing repetition counts and durations; cache round-trip
and invalidation; and no automatic interpolation/exclusion. Check concise text
at the supported 1280x900 workspace through a documented visible/manual smoke
path. Add relevant GUI behavior coverage for CI but do not run Qt/offscreen GUI
tests locally. Run focused processing plus safe static GUI checks through the
repository driver and update preflight, preprocessing-report, and user QC
documentation when implementation lands.
