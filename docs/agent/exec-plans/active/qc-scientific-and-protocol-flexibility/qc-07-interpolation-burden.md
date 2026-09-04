# QC-07: Interpolation-Burden Summary and Manual Review Above Five Percent

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-02, and QC-15.


**Status:** user accepted the direction on 2026-09-03. The user proposed a
sub-5% dataset-average target and a flag for an individual exceeding that level,
with downstream manual inclusion/exclusion. Implementation waits for the
completed cumulative plan. The metric and reporting details below are the
recommended implementation of that direction.

### Scientific Rationale and Limits

Low interpolation burden is a reasonable quality aim. However, 5% is a
transparent review threshold, not an established boundary separating valid
from invalid EEG. Volfart et al. report fewer than 5% of electrodes interpolated
per participant; that is a description of their data, not validation of a
cutoff or a cohort-average exclusion policy
([methods 2.4](https://doi.org/10.1016/j.neuroimage.2021.118228)).
Poncet et al. report a mean of 0.4 interpolated channels, range 0-2, for a
64-channel setup: calculated mean 0.625%, maximum 3.125%. These are also
descriptive results
([methods 2.5, PDF p. 4](https://15138e68bf.clvaw-cdnwnd.com/1caef9d353414e8be4f34c4530c14df0/200001944-5b24e5c251/Poncet2019.pdf)).
Both papers describe linear interpolation; the toolbox uses spherical splines.

Review should consider electrode locations and remaining donor coverage as
well as the percentage. Reconstruction quality can depend on the number and
spatial pattern of missing channels; evidence from other EEG applications does
not establish a precise FPVS reliability threshold
([Dong et al., 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8195908/)).
Do not label a participant below 5% as scientifically validated, or one above
5% as necessarily unreliable. A low dataset mean must not hide a high-burden
individual. Do not select exclusions merely to drive the mean below a target.

### Recommended Metric and Flag

Use `100 * n_successfully_interpolated_scalp / n_eligible_scalp` for each
recording. The numerator is the unique set of scalp electrodes confirmed to
have been successfully interpolated, regardless of whether they were selected
manually, by enabled experimental detection, or by kurtosis. Count overlapping
sources once. Do not substitute raw-QC candidates, intended targets, or the
existing combined removed/rejected count.

First apply QC-15's load-time requirement for a complete canonical BioSemi64
acquisition. Then freeze and record the eligible scalp set after intentional
reference/channel drops and the locked optional channel-limit stage, but before
interpolation; include bad-channel targets in that set.
Exclude mastoid references, CMS/DRL, Status, auxiliary channels, and deliberately
dropped channels. The normal full BioSemi64 analysis uses a denominator of 64.
An intentionally reduced analysis set must display its actual denominator;
unexpected missing channels or invalid geometry must not silently shrink it
into an apparently valid lower burden. QC-15 owns the blocking geometry gate;
missing burden provenance remains unavailable rather than being reported as a
low percentage.

| Successful interpolations with 64 eligible scalp channels | Percentage | New review flag |
| --- | --- | --- |
| 0 | 0% | No |
| 3 | 4.6875% | No |
| 4 | 6.25% | Yes |

Use a strict unrounded `>5%` comparison. Unknown historical outcomes, failed
repairs, or unknown denominator provenance must show unavailable/not recorded,
not zero or an inferred low percentage. QC-02 must establish truthful success
provenance before this metric can be used.

### Review, Summary, and Decision Behavior

1. Add a concise downstream review finding for each recording above 5%. For
   example: "4 of 64 scalp electrodes were interpolated (6.25%). Review before
   deciding whether to include this recording." Display the repaired electrode
   names/locations and actual outcome details in the existing review surface.
   Do not add an unsupported claim that the data are unusable.
2. Let the user retain the participant or exclude it downstream, with the reason
   and reviewed flag recorded. No automatic or preselected exclusion solely
   from this percentage. In repeated-session projects, follow QC-03: display
   participant/session/recording identity and scope the default decision to the
   affected recording. Preserve separate explicit whole-participant controls;
   one flagged visit must not silently exclude its siblings.
3. Record mean, range, number above 5%, contributing count, and unavailable
   outcome count for the identified preprocessing cohort. Count each recording
   once, not once per condition workbook. For the ordinary one-recording-per-
   participant case, this is the participant mean. Label recording averages
   explicitly in repeated-session projects; if also reporting a participant
   average, average each participant's valid recording percentages first and
   then weight participants equally. Individual recording flags remain visible
   regardless of the mean. Missing outcomes never count as zero.
4. Preserve the preprocessing-cohort summary and distinguish any later included-
   analysis-cohort summary. Record cohort identity and review provenance so a
   changed mean after exclusions cannot be mistaken for improved preprocessing.
   Applying a downstream decision preserves original EEG/workbooks and uses
   existing exclusion metadata and stale-analysis mechanisms. It must not
   silently change preprocessing time spans or trigger a repair-selection loop.
5. Keep this review criterion distinct from technical interpolation failure and
   pre-interpolation candidate-count/fraction/hemisphere/cluster findings.
   QC-08 replaces the latter automatic exclusions with review flags; those
   candidate counts still must not be substituted for confirmed successful
   interpolation. A user can explicitly exclude a recording before processing.
   The new percentage alone cannot trigger exclusion.

### Owners, Validation, and Documentation

Reuse QC-02's confirmed outcomes through `preprocess.py`, the diagnostic audit,
process-runner results/Raw cache, processing ledger, and `qc_summary_export.py`.
Use a shared structured burden result for the report and downstream review
rather than scraping workbook text. Reuse established project/recording identity
and decision persistence; integrate with the existing downstream QC review
workflow without changing frequency-domain or harmonic-selection mathematics.

Validate 0/64, 3/64, 4/64, exact 5% for a suitable intentionally reduced set,
overlapping manual/automatic/kurtosis sources, failed/missing/legacy outcomes,
and excluded auxiliary/reference channels. Verify that successfully repaired
channels remain in the denominator, repeated condition workbooks do not inflate
counts, and a flagged recording is not hidden by an average or automatically
excluded. Cover explicit inclusion/exclusion, reason persistence, reopening,
Cancel, and independent sibling recordings. Regression checks validate the
software policy, not the scientific accuracy of a 5% threshold.

Run processing focused verification and applicable static GUI/project-I/O
scopes through the repository driver. Qt execution remains CI-only; document
a visible manual review path for the flagged participant and repeated-session
cases. Update the preprocessing reporting contract, post-processing review
contract, and user methods/QC guidance when implementation lands. No active
architecture or processing behavior changes during this planning pass.
