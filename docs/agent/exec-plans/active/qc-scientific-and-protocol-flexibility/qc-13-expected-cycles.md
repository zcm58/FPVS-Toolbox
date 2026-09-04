# QC-13: Project Expected Analyzed Cycles

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-11, and QC-12 when
executing this action.

**Status:** accepted on 2026-09-03. Each project owns one expected analyzed
oddball-cycle count. FPVS Studio imports supply it from project metadata;
manually created projects require user entry. Analyzed cycles and marker counts
are separate quantities. Implementation waits for the completed plan.

## Accepted Behavior

1. Extend the project frequency protocol with a positive integer
   `expected_analyzed_oddball_cycles` and its source (`fpvs_studio_import` or
   `manual`). Define it as complete cycles in the intended FFT span, equal to
   the oddball target's FFT-bin index `k = f_oddball * N / fs`; never treat it
   as an oddball-presentation or trigger count.
   Do not add per-condition lengths. Show derived seconds read-only as
   `cycles / oddball_rate`; cycles remain the saved user-facing value.
2. Map the future FPVS Studio `project.json` field into the same normalized
   protocol. Validate imported values exactly as manual values and retain the
   Studio schema/provenance needed to diagnose a mismatch. Do not create a
   second runtime protocol model for imported projects. Reject or require
   confirmation for an ambiguous generic event/count field.
3. Require this value during manual project setup before processing. Changes
   invalidate affected preprocessing, FFT/BCA, QC, harmonic-selection, and
   Stats artifacts through the shared protocol fingerprint.
   For an existing project with no field, recover a candidate only from
   trustworthy project/run provenance, show its source and derived duration,
   and require explicit confirmation before the next processing run. If no
   trustworthy value exists, require manual entry. Preserve old outputs with
   their historical identity; never relabel them as produced from the newly
   confirmed value.
4. Before processing, compare every selected recording, condition, and
   repetition's marker-derived usable span with the declared target. Identify
   the limiting repetition. Cap longer spans to the declared target; never pad
   a short span or let a cohort-majority heuristic redefine the protocol.
5. A shorter or incompatible span is an explicit protocol mismatch requiring
   resolution through the existing review workflow before comparable group
   outputs can finalize. Report expected and available cycles, markers, sample
   span, derived seconds, and exact-bin compatibility.
6. Keep marker-derived boundaries and QC-12's exact FFT-bin rule authoritative.
   The strict-majority grid may remain a secondary corruption/legacy check,
   but the declared project target becomes the reference for managed projects.
7. Preserve raw marker count, deduplicated marker count, marker-interval count,
   realized sample count/duration, and realized analyzed cycles separately for
   each repetition. For example, 145 boundary markers delimit 144 complete
   cycles; exact-bin flooring may retain fewer. Do not aggregate unrelated
   repetition minima/maxima into one apparent interval.

## Owners and Acceptance

Implement project schema/import/manual-entry ownership in `Main_App/projects/`
and the project setup GUI. Route the expected target through preflight and
`Main_App/Shared/fft_crop_utils.py`, processing provenance, FullFFT grid QC,
review dialogs, caches, and fingerprints. Preserve the shortest-common-span
calculation only after each repetition has been checked against the declared
target; do not let one short repetition silently reduce valid siblings.

Cover manual and Studio-imported projects, save/reopen, 144 cycles at 1.2 Hz
(120 seconds), 145 markers delimiting 144 cycles, shorter protocols, exact
target spans, extra markers, a short repetition, systematic
truncation, incompatible sample counts, repeated conditions, legacy projects,
protocol edits, and unchanged valid output. Update project-I/O, FFT-crop,
preprocessing, post-processing/export, GUI, and methods-reporting contracts
when implementation lands. Run focused non-GUI checks and document a visible
GUI smoke path; Qt execution remains CI-only.
