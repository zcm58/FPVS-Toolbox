# QC Scientific Review Record

[Parent compact plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md)

This file preserves the extended audit evidence, calculations, accepted-decision explanations, and the pre-modularization checklist as of 2026-09-03. It is a reference record, not the default execution entry point. Read only the relevant subsection when an action or decision needs its original evidence.

Action modules:

- [QC-01](qc-01-transient-screening.md)
- [QC-02](qc-02-preprocessing-report.md)
- [QC-03](qc-03-recording-aware-frequency-review.md)
- [QC-04](qc-04-experimental-electrode-detector.md)
- [QC-05](qc-05-amplitude-review.md)
- [QC-06](qc-06-analyzed-intervals.md)
- [QC-07](qc-07-interpolation-burden.md)
- [QC-08](qc-08-candidate-burden-review.md)
- [QC-09](qc-09-condition-specific-warnings.md)
- [QC-10](qc-10-bca-integrity.md)
- [QC-11](qc-11-project-protocol.md)
- [QC-12](qc-12-rate-generalization.md)
- [QC-13](qc-13-expected-cycles.md)
- [QC-14](qc-14-noise-window-applicability.md)
- [QC-15](qc-15-biosemi64-geometry.md)
- [QC-16](qc-16-kurtosis-decision-gate.md)
- [QC-17](qc-17-experimental-summed-bca-review.md)
- [QC-18](qc-18-experimental-raw-spectral-review.md)
- [QC-19](qc-19-project-marker-integrity.md)
- [QC-20](qc-20-recording-condition-completeness.md)
- [QC-21](qc-21-fixed-roi-coverage.md)

---

# QC Scientific Review and Protocol Flexibility

## Status and Working Agreement

Scientific QC review completed 2026-09-03 after opening 2026-09-02.
The twenty-one-action software implementation completed on 2026-09-04;
local integrated verification also completed, while CI-only Qt/visible smoke
checks and the explicitly listed empirical work remain. The user originally
requested a read-only review of preflight and
post-processing QC, including scientific defensibility and assumptions about
presentation rate, oddball rate, and condition duration. The user subsequently
authorized this cumulative execution plan. Source code, settings, and
scientific outputs remained unchanged during the recorded planning phase.

Review issues starting with low-priority findings and nonissues; group
interrelated issues. On 2026-09-02, the user authorized automatically recording
findings recommended as no action, then pausing at the first issue requiring
manual review. Do not ask for confirmation of those no-action findings. For
each manual-review issue, explain current behavior, scientific justification,
protocol dependencies, and the recommended solution; obtain the user's
disposition before advancing. Add a separate action-item section only when the
user chooses action. The implementation details below preserve the planning
recommendations; the action modules record implemented behavior.

The user requested simpler summaries on 2026-09-03. Keep conversational review
to the concrete problem, a short recommended fix, and one decision question;
retain implementation detail and supporting evidence in this plan.

On 2026-09-03, the user accepted item 18 and emphasized that the final decision
should use more evidence, reflecting on the difficulty of automating artifact
review and interpolation selection. Use automation to assemble reproducible
measurements and suggestions, while retaining explicit review for the uncertain
exclusion rules approved here. This does not authorize converting every
automatic preprocessing operation to manual review. Evaluated automated methods
such as [PREP](https://www.frontiersin.org/journals/neuroinformatics/articles/10.3389/fninf.2015.00016/full)
and [Autoreject](https://pmc.ncbi.nlm.nih.gov/articles/PMC7243972/) show that
automation can be defensible; their validation does not transfer automatically
to these lab-calibrated rules or sustained FPVS. Manual decisions also need
consistent criteria and are not independent ground truth simply because a
reviewer accepted an automatic suggestion.

## Objective and Boundaries

Make the approved QC improvements scientifically interpretable and prepare QC
to support projects beyond 6 Hz presentation, 1.2 Hz oddball, and 120-second
conditions. A component that accepts different durations or rates is not
necessarily calibrated equally well across them.

Preserve the locked preprocessing order, exact analysis spans, scientific
exports, and versioned harmonic-selection methods except where a later approved
action explicitly scopes a change and its required contract updates. Do not
access `src/Standalone_Scripts/**`, recreate retired packages, or run local
offscreen/Qt tests. No new automatic rejection or interpolation policy is
authorized by the first action item.

## Review Decision Ledger

| Review item | Topic | Disposition |
| --- | --- | --- |
| 1 | Header-only BDF detection and recording-not-started explanation | Closed, no action. User accepted the explanation as matching the lab's likely failure mode. |
| 2 | Condition-aware preflight cache identity | Closed, no action. Retain the design; future rate plumbing must supply the intended project inputs to it. |
| 3 | Time-domain window length, overlap, and transient threshold calibration | Action approved in principle. User prefers 5-second windows with 50% overlap; detailed recommendation is QC-01 below. |
| 4 | Post-preprocessing metadata consistency audit | Closed, no action. Retain the warning-only checks against supplied preprocessing settings; they do not independently validate signal quality. |
| 5 | Canonical harmonic list, exact selected-column requirements, and stale-output guards | Closed, no action to this safeguard. Preserve explicit failure for missing selected columns. QC-10 through QC-14 and QC-17 later resolve the rate, selection, and nonfinite policies. |
| 6 | Canonical project identities and recording-specific manual metadata | Closed automatically, no action to identity precedence. Preserve dataset-index participant/group/recording identity and recording-level manual overrides before participant fallback. QC-04 later resolves detector mode and opt-out behavior. |
| 7 | Original automatic suggestions versus user review decisions | Closed automatically, no action. Preserve original, accepted/rejected, and manually added flags separately. Acceptance alone is not independent ground truth for accuracy claims. |
| 8 | Original spectra and exclusion metadata kept separately | Closed automatically, no action. Preserve original processed workbooks and full-audit visibility of active/excluded observations. Later QC actions define exclusion authority without changing this preservation rule. |
| 9 | Condition buffering, bounded background execution, and cancellation | Closed automatically, no additional action. Preserve RAM/memmap equivalence, condition-only reads, bounded concurrency, deterministic order, and cleanup. QC-01 already covers the extra window workload and I/O/scoring separation. |
| 10 | Processing QC Summary: processing inclusion and interpolation outcome claims | Action accepted on 2026-09-03. User agreed to label it a preprocessing report; QC-02 records that decision and the recommended supporting outcome/provenance corrections. |
| 11 | Recording-aware frequency-domain QC review for repeated-session projects | Action accepted on 2026-09-03. Show and review each affected recording, with manual exclusion scoped to that recording; see QC-03. |
| 12 | Experimental removed-electrode detector and reliable opt-out | Feature direction, existing-project migration, separation from amplitude/transient screens, and the final On/Off authority map are recorded in QC-04. |
| 13 | Severe raw recording-amplitude flags: authority to exclude | Accepted on 2026-09-03: flag for review, with brief GUI explanation and BioSemi links; exclusion requires a user decision. See QC-05. |
| 14 | Analyzed-interval boundary for all signal-based QC | Accepted and broadened by the user on 2026-09-03: score only the analyzed intervals, including experimental channel detection and preprocessing kurtosis. See QC-06. |
| 15 | Processing scope, interpolation, and continuous filtering context | Partly resolved by the user on 2026-09-03: restrict bad-channel decisions to analyzed samples; no change to interpolation application. The separate investigation continues for FIR/notch filtering, resampling, and analysis boundaries. Failure handling remains item 16. |
| 16 | Additional montage correction and interpolation-retry workflow | Closed with no separate montage editor or repair-retry workflow. QC-15 later supersedes the earlier permissive montage handling: unsupported or mismatched geometry blocks processing, while QC-02 reports actual interpolation outcomes and QC-07 never treats failed/unknown repair as zero burden. |
| 17 | Interpolation burden: participant review above 5% | Direction accepted on 2026-09-03. Report the dataset mean and flag individual burden above 5% for downstream manual inclusion/exclusion. For 64 scalp electrodes, the flag starts at four successful interpolations. See QC-07; no automatic exclusion solely on this measure. |
| 18 | Existing automatic candidate-count, fraction, hemisphere, and cluster exclusions | Accepted on 2026-09-03: replace these automatic exclusions with recording-level review flags, allow explicit early exclusion or continuation, and use actual processing outcomes for the final review. The runner must honor continuation. See QC-08; preserve measurements and existing independent technical failure handling. |
| 19 | Separate persistent candidates from condition-specific findings | Closed automatically, no additional action to replace persistence with majority voting. Retain the conservative same-category/all-observed-occurrences nomination rule under experimental detection; it is not proof of physical removal or continuous impairment. QC-09 owns local visibility and QC-04/QC-16 own calibration and action authority. |
| 20 | Dynamic base-frequency overlap exclusion | Closed automatically, no action to this mechanism. It excludes positive integer multiples of the supplied presentation frequency rather than a fixed 6/12/18-Hz list. QC-11/QC-12 later resolve project propagation and QC-14 owns exact-bin applicability. |
| 21 | Full-condition channel findings omitted from ordinary review when other conditions look normal | Accepted on 2026-09-03. Clearly warn when an electrode was flagged in one particular condition but not all conditions, showing the affected condition/occurrence and evaluated comparison scope. Keep persistent interpolation suggestions separate and retain detector opt-out. See QC-09; this visibility does not by itself authorize interpolation or exclusion, while QC-16 owns any later corroborated repair. |
| 22 | Incomplete/nonfinite values inside present BCA harmonic columns | Accepted on 2026-09-03. Treat this abnormal state as a technical output-integrity failure requiring regeneration/investigation. Do not calculate a partial sum, fill with zero, or create a scientific inclusion/exclusion decision. Add a finite-data guard before new BCA workbooks are written. See QC-10. |
| 23 | Direct 120-second condition-duration lock | Closed automatically, no action. Active FFT cropping is marker-derived and exact-bin aligned. QC-13/QC-14 later define expected-cycle, heterogeneous-span, and duration-dependent noise applicability. |
| 24 | Project ownership of presentation and oddball rates | Accepted on 2026-09-03 and clarified on 2026-09-04. Store one project-wide rate protocol and use it across all stages; projects remain independent and condition-level overrides are out of scope. There is no universal 16.8-Hz analysis ceiling. See QC-11/QC-12. |
| 25 | Generalize presentation/oddball rates and user entry | Accepted in direction on 2026-09-03. Support recurrence-count entry and direct oddball-frequency entry, remove active 1.2-Hz locks, and propagate the project protocol throughout. Direct-input relationship validation remains item 26. See QC-12. |
| 26 | Validation of direct oddball-frequency entry | Accepted on 2026-09-03. The entered rate must resolve to a whole-number stimulus recurrence; show the derived `N`, reject incompatible pairs, and never silently round. QC-12 is now fully specified. |
| 27 | Project-owned expected analyzed length | Accepted in direction on 2026-09-03. Store one project-wide oddball-cycle count, import it from future FPVS Studio `project.json` metadata, and require manual-project users to enter it. Seconds are derived only. See QC-13; cycle/event semantics remain item 28. |
| 28 | Meaning of expected analyzed oddball cycles | Accepted on 2026-09-03. Count complete cycles in the FFT span; keep oddball presentation and marker counts separate. A 120-second span at 1.2 Hz is 144 cycles, while 145 boundary markers delimit those 144 cycles. QC-13 is now fully specified. |
| 29 | Fixed neighboring-noise bins across durations | Accepted on 2026-09-03 as an edge-case safeguard. Keep the versioned +/-10-bin method, require complete uncontaminated support, report its physical width, and reserve alternatives for empirical calibration. See QC-14. |
| 30 | BioSemi64 coordinate geometry | Accepted on 2026-09-03 as QC-15 and execution priority 1. BioSemi ActiveTwo 64 is the sole supported project montage for now; correct geometry, prevent mixed provenance, and assess legacy outputs. |
| 31 | Independent kurtosis bad-channel rule | Accepted on 2026-09-03 as QC-16. Kurtosis plus an eligible independent method can trigger automatic interpolation; kurtosis alone requires explicit GUI review. |
| 32 | Frequency-QC technical scaffolding | Closed automatically, no action. Preserve exact columns, fingerprints and stale guards, original outputs, provenance separation, and recording-scoped backend identity. |
| 33 | Summed-BCA magnitude authority | Accepted on 2026-09-03 as QC-17. Keep the rough values as project-owned experimental GUI review defaults; summed BCA alone cannot exclude data. Place the feature under Experimental settings. |
| 34 | FullFFT grid validation | Closed automatically, no additional action. Preserve exact technical grid checks and explicit/manual exclusions; QC-12/QC-13 own rate and expected-cycle changes. |
| 35 | Harmonic-profile identity | Closed automatically, no action. Preserve the four versioned methods and canonical selection/freshness contracts. |
| 36 | Stats finite-DV integrity/outlier stage | Closed automatically, no action. Finite magnitude crossings remain flags; nonfinite unusable DVs remain required exclusions. |
| 37 | Separate Stats cohort-relative BCA screen | Accepted on 2026-09-03 as an expansion of QC-17. Preserve the cohort-relative view as optional experimental context using canonical final harmonics; remove the duplicate exclusion-named state. |
| 38 | Experimental detector percentages | Accepted on 2026-09-03 as an expansion of QC-04. Retain the percentages as internal in-lab validation results, publish a reproducible calibration receipt, and rerun them after the planned method changes. |
| 39 | Preflight scan unavailable or failed | Closed automatically, no additional action. Preserve explicit Continue/Cancel acknowledgement; QC-02 must report `not evaluated` and the reason rather than pass. |
| 40 | Condition-aware raw-spectral screening | Accepted on 2026-09-03 as QC-18. Keep it experimental and review-only, use canonical project targets, and expose notch/FPVS conflicts. |
| 41 | Oddball marker identity and missing-marker gaps | Accepted on 2026-09-03 as QC-19. Use one project code defaulting to 55, remove code guessing and broad deduplication, and pause unexplained gaps for GUI review. |
| 42 | Recording-condition output completeness | Accepted on 2026-09-03 as QC-20. Require every expected cell to be accounted for, allowing explicit no-output states while blocking unexplained or stale results. |
| 43 | Fixed ROI electrode coverage | Accepted on 2026-09-03 as QC-21. Require every primary ROI's complete unique canonical set, counting successful interpolation as present and leaving a valid affected cell unavailable. |
| 44 | Whole-scalp-normalized ROI values after an electrode exclusion | Accepted on 2026-09-03 as an expansion of QC-21. If any member of the frozen whole-scalp denominator is unavailable, do not calculate any normalized ROI derivative for that recording-condition. Complete raw ROIs unaffected by that electrode remain available; successful interpolation counts as present. |
| 45 | Universal 16.8-Hz analysis ceiling | Corrected on 2026-09-04. The user did not approve a project-global BCA ceiling and clarified that 16.8 Hz must not be universal. QC-11 owns rates only; an old artifact's actual limit remains provenance only. |
| 46 | Filter-owned analysis support | Finalized on 2026-09-04. Remove the live 16.8-Hz default, generic ceiling GUI/control path, competing 40-Hz fallback, and independent target rebuilding. One shared QC-12 resolver supplies exact harmonics only when the target and complete +/-10-bin neighborhood fall within the project's applied filter range and Nyquist. |
| 47 | Notch overlap with FPVS targets/noise bins | Finalized on 2026-09-04. Keep configured effective 50/60-Hz line-noise notches and their applicable harmonics even when they overlap base/oddball targets. Mark a directly notched target or a score with a notched required noise bin unavailable, retain the rest of the recording-condition, and never count the hole as an adaptive failure. |

The one-item QC review is complete. The accepted actions remain future
implementation work; this record does not itself change runtime behavior.

### Evidence and Scope of Automatic No-Action Closures

- Item 5: `canonical_harmonics.py` selection identity and
  `artifact_freshness.py` registered-output checks, plus
  `frequency_domain_qc.py` exact selected-column lookup. This does not validate
  the scientific selection or prove that artifact contents were not modified
  externally.
- Item 6: `process_runner.py` recording-specific manual resolution and
  `frequency_domain_qc.py` project dataset-index validation. This does not close
  the recording-aware GUI review issue.
- Item 7: `removed_electrode_detection.py` review-record builder. The storage
  design is appropriate; detector accuracy and experimental labeling remain
  separate decisions.
- Item 8: `frequency_domain_qc.py` decision persistence and
  `analysis_ready_workbook.py` full-audit cohort/recording rows. This does not
  close misleading claims in the earlier Processing QC Summary.
- Item 9: `preflight_qc.py` condition buffer and scan orchestration. Exact
  full-condition statistics and shared analysis spans are already preservation
  requirements in QC-01; QC-06/QC-19 later resolve their crop ownership and
  the action modules assign threshold calibration.
- Item 19: `raw_channel_qc.py:462` intersects each category separately across
  all supplied condition occurrences. That distinction is a reasonable
  conservative nomination policy, not independently validated classification.
  A single occurrence necessarily meets the all-occurrences criterion when
  flagged; alternating categories do not. This scoped closure does not approve
  hiding local findings or prove equal calibration across repetition counts,
  condition mixtures, and durations. Keep isolated quiet-window metrics from
  being promoted to removed-electrode claims merely through this review.
- Item 20: `dv_policy_group_significant.py:3544` compares a frequency to a
  positive integer multiple of its supplied base frequency; the selection
  loop excludes matched overlaps around line 1474. Preserve this locked
  safeguard. This does not establish that all callers supply project-owned
  rates or that current tolerances are suitable for every future protocol.

### Related Investigation: Item 15, Processing Scope

The user has approved excluding setup, breaks, discarded tails, and other
unanalyzed intervals from direct signal-based QC scoring. QC-06 applies that
decision to the related raw-detector and kurtosis paths as well as amplitude.

Continuous preprocessing still uses surrounding data: the FIR and resampling
mix samples across time, and the optional FFT multi-notch transforms an entire
contiguous segment. Activity outside a retained interval can therefore affect
processed values inside it. The influence is not necessarily limited to a few
boundary samples, especially with the segment-wide FFT operation. Restricting
QC inputs does not by itself guarantee zero outside influence on final EEG.
See `preprocess.py` around lines 601, 694, and 767, and `fft_multinotch.py`
around lines 190-203 and 314-317. MNE's
[filtering background](https://mne.tools/stable/auto_tutorials/preprocessing/25_background_filtering.html)
explains temporal spreading and filtering edge effects.

The user explicitly reopened the earlier no-action closure to investigate
whether each processing operation should be limited to analysis windows,
including whether interpolation should be period-specific. The separate
[analysis-window preprocessing scope plan](../../future/analysis-window-preprocessing-scope.md)
records code evidence, published precedents, counterarguments, and planned
comparisons. It separates bad-channel selection, fixed spatial interpolation,
time-varying repair masks, and temporal filtering/resampling.

The user subsequently settled the interpolation question: restrict bad-channel
decisions to analyzed periods and leave the current interpolation application
unchanged. Preserve its continuous-Raw spatial repair and pipeline position;
do not introduce interval-only writes or condition-specific repair maps.
QC-06 records the scoring change. Existing failure handling is retained under
item 16's later no-additional-action closure.

The investigation now focuses on FIR/notch filtering, resampling, and analysis
boundaries. Continuous filtering has legitimate boundary-related reasons as
well as possible outside-artifact influence. Finalize those remaining choices
from the investigation; neither published precedent nor this interpolation
decision establishes that all temporal processing should stay unchanged.

### No-Additional-Action Closure: Item 16, Montage and Interpolation Failures

When interpolation raises an exception, preprocessing logs a warning and
continues. It also continues when intended bad channels cannot be interpolated
because the montage is missing (`preprocess.py`, around lines 934-1020).
QC-02 corrects the reporting of these outcomes. Accurate reporting alone does
not establish that the intended preprocessing was completed; nevertheless, no
new continuation/stop policy is included in this update under this closure.

The user clarified the lab setup: BioSemi ActiveTwo, 64 scalp electrodes,
CMS/DRL, and mastoid references. The loader uses `standard_1005`, whose names
cover the standard BioSemi64 scalp names. Selected reference channels (normally
EXG1/EXG2) need no scalp coordinates for the pointwise initial reference and
are dropped before interpolation. A missing-position warning confined to those
selected references is deliberately suppressed when the parser recognizes it.
Keep that omission permitted; absent reference signal channels are a different
issue. CMS/DRL form the hardware feedback pair and do not add two channels to
the 64-scalp interpolation denominator; see
[BioSemi's explanation](https://www.biosemi.com/faq/cms%26drl.htm).

Unexpected missing scalp coordinates are also currently allowed past loading:
`Shared/load_utils.py:312` uses `on_missing="warn"`, and the montage exception
handler around line 675 warns and returns Raw. Unmatched EEG labels can receive
NaN coordinates. Depending on which coordinates are missing, interpolation can
raise or produce invalid output without raising. The runner also assumes the
first 64 file channels are the intended scalp set; it does not validate that
identity merely by selecting them. These facts do not establish that the lab's
normal files actually have this problem. Matching label coverage also does not
establish that `standard_1005` and `biosemi64` have identical coordinates; the
template-choice question was unresolved at this point and was later resolved
by QC-15.

The user questioned the need for this added workflow because current validated
support is limited to BioSemi ActiveTwo64 files with standard electrode names,
as documented in `docs/user/index.md:76`. For those files the loader assigns
the template automatically. The settings surface's montage control manages
ROI presets, not preprocessing coordinates; it is not a user-facing repair
route. There is no routine file-correction procedure to prescribe without an
actual error. Troubleshooting a reproducible failure would distinguish
nonstandard channel labels/configuration from an application-loading defect;
users should not be asked to edit their original EEG recordings speculatively.

**Recommendation at this review point: no additional correction workflow.** Withdraw the
proposed montage editor/correction workflow, extra blocking validation, and
new stop/retry policy. Keep existing loading and interpolation handling, with
QC-02's already approved truthful success/failure/skipped provenance. QC-07's
successful-interpolation percentage cannot turn unknown or failed outcomes
into a reassuring zero. This disposition narrows the work to demonstrated
needs; it does not claim that a physical headset guarantees perfect metadata
or that an exception can never occur. At that point, the plan deferred action
until a reproducible failure, geometry finding, or future hardware expansion.
The subsequent coordinate audit established that the active loader used
`standard_1005`; the user then approved QC-15, which supersedes the permissive
geometry portion of this recommendation while retaining the decision against a
general editor and speculative source-file repair workflow.

### Accepted Decision: Item 18, Automatic Burden Exclusions

The raw-QC runner can reject a recording before interpolation, independently
of QC-07's later successful-interpolation review. The related default rules in
`raw_channel_qc.py:95` and comparisons around line 1259 are:

| Rule | Default trigger | Interpretation for the standard 64 scalp channels |
| --- | --- | --- |
| Candidate count | More than 20; configurable | 21 or more candidates |
| Candidate fraction | More than 50% | 33 or more; redundant with the default count rule |
| Hemisphere burden | At least 50% of a hemisphere, with at least 8 hemisphere channels present | 14 of 27 left or right channels |
| Connected cluster | At least 6 neighboring candidates | Six connected electrodes; four or five currently warn |

Candidates are not confirmed successful interpolations. Auto combines inferred
low-variance, high-amplitude, rare-burst, and spatial candidates with manual
entries. Current Manual and Off modes still allow inferred low-variance
candidates into some rules; QC-04 already requires fixing this opt-out problem.
The cluster rule runs in Auto/Manual and includes existing bad channels.
Their counts depend on upstream detection/sampling, even though the burden
formulas do not explicitly assume 6 Hz, 1.2 Hz, or 120 seconds.

**Accepted solution:** convert these four related heuristic
threshold crossings to recording-level review flags, retaining counts,
locations, severity, and reasons, with inclusion/exclusion explicitly decided
by the user. Concentrated or extensive bad channels are meaningful concerns,
but these particular thresholds do not establish universal unusability. This
would align their decision authority with the accepted review approach while
keeping candidate burden distinct from the actual outcome reported by QC-07.
Do not imply that a manual inclusion guarantees successful or reliable
interpolation, suppress an independent technical failure, or change the
interpolation algorithm. The user approved this direction on 2026-09-03;
QC-08 below records the implementation plan.

**Explanation requested during review:** the candidate union above is broader
than the raw-QC interpolation target list, which currently contains manual
entries and, in Auto mode, inferred low-variance channels. High-amplitude,
rare-burst, and spatial candidates can therefore contribute to an exclusion
without being selected for interpolation by this stage. A connected group of
six candidates can reject the file without establishing that six scalp
electrodes actually require or receive repair. The runner returns an excluded
result before preprocessing, so this run produces no new processed conditions
or FFT outputs for that recording; it does not delete the original BDF. Ledger
reconciliation removes previously generated expected outputs for a recording
newly excluded in this run (`processing_ledger.py:1278`). Accepting a preflight
channel list currently does not override these runner gates; six connected
manual targets can still cause rejection before interpolation.

The concern behind these checks is scientifically reasonable: extensive or
concentrated electrode loss can leave too little spatial information for
reliable reconstruction. The number and distribution matter, but evidence
from other EEG applications does not validate these exact FPVS exclusion
cutoffs ([Dong et al., 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8195908/)).
Overly authoritative candidate gates could discard usable recordings and
reduce the analysis sample; systematic selection bias would depend on which
recordings are lost and is not established by this code audit. Conversely,
manual inclusion does not establish that a seriously degraded recording is
reliable.

**Accepted workflow:** retain the pre-processing
findings and let the user explicitly exclude the affected recording or
continue after reviewing counts, locations, and reasons. A decision to
continue must be honored by the runner rather than encountering the same
automatic heuristic exclusion again. Continuing must not automatically turn
all candidates into interpolation targets. After processing, use QC-02's
actual outcomes and QC-07's successful-interpolation burden for downstream
review. Apply QC-06's already approved analyzed-interval scoring throughout.
This is an approved review policy, not an empirically validated optimum or a
new technical failure-handling policy. Implementation waits for completion of
the cumulative plan.

Migration must explicitly reconsider prior automatic heuristic
exclusions while preserving explicit manual decisions and independent
technical failures. Existing excluded ledger entries are reused before
processing-fingerprint comparisons when the raw file is unchanged
(`processing_ledger.py:612`), so a fingerprint/version bump alone would not
bring those recordings back into review.

### Accepted Decision: Item 21, Condition-Specific Visibility

Full-condition classification already stores low-variance, high-amplitude,
and rare-burst findings per analyzed condition occurrence
(`raw_channel_qc.py:1720`). However, `_review_rules` around line 1565 only
surfaces the same-category intersection across every occurrence. High-amplitude
and rare-burst short-window findings can independently trigger review, but
short-window low-variance flags are deliberately suppressed around line 1817.

An electrode can therefore be flagged as low variance across condition A and
normal across condition B without creating an ordinary channel-review warning.
If nothing else triggers, the top-level result can say "passed" (around line
573). The A finding remains in the detailed payload, but the normal GUI review
is driven by `suspicious_results` and warning rules
(`gui/preprocessing_qc_workflow.py:2661`). This conflicts with the active
condition-aware preflight plan's stated intent that occurrence-specific
findings remain separately reported review signals.

**Accepted solution:** surface any full-occurrence
finding from an enabled detector as a review entry with recording, condition,
repetition, electrode, category, measured values, and analyzed span. An overall
clear result must not conceal that finding. Keep the persistent candidate list
separate; this visibility change must not preselect whole-recording
interpolation, automatically exclude a condition/recording, or enable a detector
that the user has switched off. Preserve the existing separate transient
review and the accepted fixed interpolation application. The user approved this
direction on 2026-09-03 and required the limited condition scope to be clear and
apparent. QC-09 below records the implementation plan.

The visibility issue is protocol-related: adding a normal occurrence can remove
an existing persistent warning, and changing durations can change full-span
metrics. Showing each occurrence preserves the evidence without inventing a
new voting percentage or claiming equal detector accuracy across protocols.
The numerical classifications and their calibration remain separate work.

Use direct scope wording such as: **"P7 was flagged as potentially bad in
Condition A, occurrence 1 only. It was not flagged in the other 3 evaluated
occurrences."** Accompany it with a brief explanation that the flag describes
the condition-occurrence statistic; it does not prove continuous impairment
throughout that interval or prove that unflagged data are artifact-free.
Never describe an unavailable/unscanned occurrence as unflagged.

### Accepted Decision: Item 22, Incomplete BCA Values

Frequency-domain QC selects exact harmonic columns, converts their cells to
numbers, turns nonnumeric and infinite values into missing values, and then
sums with `min_count=1` (`frequency_domain_qc.py:884-892`). Thus one finite
selected harmonic is enough to create a score. If every selected value for an
electrode is missing, its nonfinite sum is silently skipped. Participant or
recording summaries are built only from threshold flags, so an incomplete row
can produce no warning or review requirement.

The user correctly questioned why the active pipeline would produce such a
cell after bad-channel interpolation. Successful interpolation replaces bad
EEG samples with numeric estimates and clears their bad status. With finite
BioSemi input and finite processing results, post-processing constructs a dense
numeric BCA matrix and should write every present electrode-frequency cell.
There is no normal `bad electrode -> blank BCA cell` behavior. If interpolation
fails and the channel remains marked bad, the active Epochs export normally
omits that channel row (`post_process.py:62-70`), rather than writing an
isolated blank cell.

This is different from the already settled exact-column safeguard: the column
headings can all exist while one or more cells inside them are blank, text,
NaN, or infinite. Comparing a partial sum with a complete-sum threshold changes
the meaning of the measure. It can hide a warning (for example, selected values
4, 8, and 5 uV sum to 17 uV, but losing the 8-uV value leaves 9 uV below the
current 10-uV warning threshold). Because BCA values can be signed, omitted
values can also increase the absolute partial sum by removing cancellation.
The plausible routes are abnormal: nonfinite samples or numerical output
propagating through epoch averaging/FFT, invalid interpolation output that did
not raise, an old/malformed/externally edited workbook, or a software defect.
The code has no final finite-value gate before BCA export. Normal BioSemi BDF
data make this unlikely; the audit establishes the possible software behavior,
not that current project workbooks contain it. The later full-audit analysis-
ready exporter already identifies nonfinite source cells, but that does not
correct the earlier frequency-QC partial-sum comparison.

**Accepted solution:** treat any nonfinite selected
BCA cell as a technical output-integrity failure, not a routine artifact-review
choice. Identify recording/participant, condition, electrode, workbook, and
affected harmonic cells; calculate no partial score and create no automatic
clean/exclusion decision from it. Complete rows may still be reported for
diagnosis, but the frequency-QC result remains incomplete and cannot be
finalized until the affected output is regenerated or the defect is resolved.
Do not fill with zero or ask the user to scientifically include an undefined
score. Also validate finite data before writing new BCA workbooks so active-run
failures are caught at their source. The user approved this safeguard on
2026-09-03; QC-10 below records its execution plan.

The original unresolved list in this location was later resolved by QC-11
through QC-17. The current five-point queue appears after Item 37 below.

---

## Consolidation and Execution Checklist

- [x] Record the first two accepted no-action decisions.
- [x] Add QC-01 with the user's preferred 5-second/50% design direction.
- [x] Record accepted item 5 and the automatically closed no-action findings;
  retain their scoped exclusions from unresolved scientific-policy questions.
- [x] Add QC-02 after the user accepted the preprocessing-report label.
- [x] Add QC-03 after the user accepted recording-specific review/exclusion.
- [x] Add QC-04 after the user accepted experimental, opt-in detection;
  retain the accepted new-project default and independent manual lists.
- [x] Record accepted existing-project migration and independent amplitude-QC
  function.
- [x] Add QC-05 after the user accepted a severe-amplitude flag and brief GUI
  explanation with BioSemi links.
- [x] Add QC-06 after the user broadened analyzed-interval scoring to all
  signal-based QC; reconcile earlier sampler-preservation statements.
- [x] Reopen item 15 at the user's request and create the separate scientific
  investigation plan; preserve QC-06's accepted scoring direction.
- [x] Record the user's decision to keep interpolation application unchanged;
  narrow the remaining investigation to temporal processing and boundaries.
- [x] Add QC-07 for the user-proposed >5% interpolation-burden review flag and
  dataset summary; keep technical montage/interpolation failure separate.
- [x] Close item 16 with no additional workflow or blocking changes for the
  current supported BioSemi64 scope; keep truthful outcome reporting.
- [x] Add QC-08 after the user accepted review flags and decisions using more
  evidence for candidate-count/fraction/hemisphere/cluster findings.
- [x] Automatically close the scoped persistence-distinction and dynamic
  base-overlap nonissues; retain their calibration/input dependencies.
- [x] Add QC-09 after the user accepted prominent condition-specific electrode
  warnings distinct from across-condition persistent findings.
- [x] Add QC-10 after the user accepted a finite-BCA output-integrity safeguard
  and rejected partial-sum handling of abnormal blank/nonfinite cells.
- [x] Add QC-11 after the user accepted one independent, project-wide
  presentation/oddball-rate protocol with no condition overrides; later remove
  the assistant-inferred universal ceiling after the user's clarification.
- [x] Continue the review, automatically closing no-action findings and taking
  one manual decision at a time; append approved actions.
- [x] Resolve dependencies, required inputs, acceptance criteria, and execution
  order across approved items; finalize this plan before starting source edits.
- [x] Move the finalized plan to `active/` and implement in bounded sections.
- [x] Complete the applicable local software checks and explicitly identify the
  unmet empirical requirements retained in the parent plan. CI-only Qt and
  visible/manual smoke verification remain release work.

---

## Review Continuation: Items 23-24

### Item 23 - No Direct 120-Second Crop Lock (No Action)

The active FFT crop derives each repetition from oddball markers and rounds
down to an exact-bin-compatible sample count. Repetitions within a condition
then use the shortest common valid length. It does not require a 120-second
recording. Keep this behavior: exact-bin alignment is appropriate for the
current Fourier analysis.

This scoped no-action decision does not settle two duration-sensitive policies:

- cohort grid QC may flag deliberately heterogeneous analyzed durations; and
- the fixed neighboring-bin count spans a different physical bandwidth when
  analyzed duration changes.

Those remain later scientific-review items.

### Item 24 - Project-Owned Protocol Values (Accepted)

The presentation rate is editable but stored in application-wide settings.
Processing copies it at launch, while later frequency QC, harmonic selection,
and provenance independently reread the current application value. An older
project can therefore be reopened after the global setting changed and be
reviewed or described with a rate different from its processing run.

The oddball rate is more restrictive: the GUI, validators, cropping, BCA
generation, grid QC, provenance, and Stats contain independent 1.2-Hz locks.
The legacy BCA ceiling is also application-wide, and its 16.8-Hz normal default
conflicts with a 40-Hz fallback in another configuration path.

The original recommendation bundled that ceiling into a project protocol. The
rate-ownership portion remains sound: give each project one validated
presentation/oddball-rate snapshot and pass it through processing, exports,
provenance, QC, and Stats. Harmonic-domain ownership is a separate statistical
method question.

**Decision, corrected on 2026-09-04:** projects must remain independent. Each
project has one presentation rate and one oddball-rate definition;
condition-level rate overrides are not required. The user explicitly clarified
that there is no universal 16.8-Hz analysis ceiling. QC-11 owns the rates;
QC-12 owns the versioned harmonic-domain replacement.

### Item 25 - Presentation-to-Oddball Relationship (Approved in QC-12)

In the current FPVS design, an oddball embedded every integer number `N` of
stimuli has the exact rate `presentation_rate / N`. The present 6-Hz stream
with every fifth item oddball yields 1.2 Hz; published work also uses a 10-Hz
stream with every fifth item oddball, yielding 2 Hz. These are protocol inputs,
not universal FPVS constants.

Storing two unconstrained decimal inputs could admit a pair that cannot be
produced by an oddball embedded in the regular stream. It can also create a
large exact-bin crop step and ambiguous overlap identity. Recommended current
scope: store the presentation rate and integer `oddball_every_n`, derive the
exact oddball rate, and verify marker spacing against the declared recurrence.
Keep independent dual-frequency paradigms as later scope if needed.

Once this relationship is decided, the same action can replace hardcoded 1.2
in cropping, marker checks, FFT/BCA targets, labels, grid QC, provenance, and
Stats; generate harmonics inside the selected profile's declared domain and
technically usable spectrum; and replace the literal 1.2-Hz fixed-profile
defaults with protocol-aware harmonic identity.
Exact-bin behavior remains required, with no nearest-bin fallback.

Scientific examples: [de Heering and Rossion (2015)](https://elifesciences.org/articles/06564)
used 6/1.2 Hz, while [Lochy et al. (2015)](https://orbilu.uni.lu/handle/10993/36831)
used 10/2 Hz, both with every fifth item as the oddball.

**Decision:** accepted in direction on 2026-09-03. The user confirmed that a
3-Hz stream with an oddball every tenth stimulus should resolve easily to
0.3 Hz, and also required an option to enter oddball frequency directly.
QC-12 groups the interdependent rate consumers, eligible harmonic-domain
calculation, and fixed-profile identity. Item 26 decides how direct input is
validated.

### Item 26 - Direct Oddball-Frequency Validation (Approved in QC-12)

Two entry methods can remain equivalent if a directly entered oddball rate is
required to imply a whole-number recurrence. For example, base 3 Hz plus
oddball 0.3 Hz resolves to every tenth stimulus. Base 3 Hz plus oddball 0.4 Hz
would imply every 7.5 stimuli and cannot describe one periodic oddball embedded
in a regular 3-Hz stream.

Recommended current boundary: accept direct Hz entry when the ratio resolves
to an integer recurrence within a documented numerical tolerance; derive and
show `N`; otherwise reject without rounding and explain the nearest valid
choices. Supporting a genuinely independent second frequency would require a
different event/timing model and remains future scope unless the user needs it
now.

**Decision:** accepted on 2026-09-03. Direct oddball-frequency input must
resolve to a whole-number recurrence. QC-12 uses only an input/display-scale
tolerance, canonicalizes the saved value to the exact derived rate, and keeps
independently timed dual-frequency paradigms out of current scope.

### Item 27 - Expected Analyzed Condition Length (Approved in QC-13)

Marker-derived cropping already supports non-120-second data, but the project
does not declare its intended analyzed length. FullFFT grid QC instead treats a
strict-majority cycle count across active participant-condition workbooks as
the reference. That detects isolated mismatches but can accept a systematic
truncation, flag a correct minority, or obscure which short repetition forced
all repetitions of one condition to the shared minimum.

Recommended safeguard: store one project-wide expected analyzed length as an
exact compatible oddball-cycle count, while allowing seconds or cycles as the
user input/display. Check every repetition against it. Cap a longer usable span
at the declared target; identify and flag a shorter limiting repetition for
manual recording-condition review. Never pad data or replace marker-derived
boundaries/exact-bin validation. Per-condition target lengths remain future
scope, and the fixed neighboring-bin bandwidth is a separate method decision.

**Decision:** accepted in direction on 2026-09-03. The canonical project value
is an expected oddball-cycle count rather than seconds. Future FPVS Studio
imports provide it from `project.json`; manual projects require project-level
entry. QC-13 records the action. Item 28 resolves the off-by-one distinction
between complete analyzed cycles and oddball presentation/marker count.

### Item 28 - Analyzed Cycles Versus Markers (Approved in QC-13)

One complete Fourier cycle is the interval between two equivalent oddball
phase points. Consequently, 145 correctly spaced oddball markers delimit 144
complete marker-to-marker cycles. The active crop already records marker count
separately and defines available marker intervals as `markers - 1`; exact-bin
flooring can make the final analyzed FFT-cycle count smaller still.

Recommended definition: `expected_analyzed_oddball_cycles` is the exact number of
complete cycles intended in the analyzed FFT span, equal to the oddball target's
FFT-bin index. Keep `expected_oddball_presentations` or observed marker count as
separate provenance/QC where available. FPVS Studio and manual inputs must use
the same definition so no importer adds or removes one cycle silently.

**Decision:** accepted on 2026-09-03. The project field means complete analyzed
FFT cycles. Marker and presentation counts remain separately named diagnostics;
ambiguous imported counts cannot be converted silently. QC-13 is finalized.

### Item 29 - Duration-Sensitive Neighboring Noise (Approved as QC-14)

The locked BCA/z-score baseline examines target +/-10 FFT bins, excludes the
target and its immediate neighbors, then drops one minimum and maximum. This
leaves 16 reference amplitudes when the complete neighborhood is available.
Because FFT spacing is `1 / analyzed_seconds`, the half-width is 0.0833 Hz at
120 seconds, 0.1667 Hz at 60 seconds, 0.3333 Hz at 30 seconds, and 0.5 Hz at
20 seconds.

Fixed-bin local baselines have direct FPVS precedent across several analyzed
durations. They also keep the number of reference observations stable. A
fixed-Hz replacement would vary that count and change the noise mean/SD and
the interpretation of the locked z threshold, so it needs empirical
recalibration rather than a silent substitution. The SSVEP review by
[Norcia et al. (2015)](https://doi.org/10.1167/15.6.4) specifically conditions
local noise estimation on avoiding stimulation harmonics. General spectral
guidance also requires reporting analyzed duration and resulting resolution
([Keil et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9717489/)).

Recommended current policy: retain the versioned +/-10-bin method, report its
realized Hz width, and require a complete finite neighborhood with clearance
from DC, Nyquist, and every declared base/oddball harmonic. In particular, the
analyzed oddball-cycle count must exceed 10 so an adjacent oddball harmonic
cannot enter the window. If the method is inapplicable, do not calculate a
standard BCA/z result; require a longer protocol or a future separately
validated duration-aware method. Plan empirical type-I-error and sensitivity
comparisons before offering fixed-Hz or adaptive-bin alternatives.

**Decision:** accepted on 2026-09-03. This is an edge-case safeguard because
ordinary conditions are not expected below about 60 seconds. QC-14 uses the
scientifically relevant cycle/bin checks instead of imposing 60 seconds as a
hard minimum and does not change valid +/-10-bin results.

### Item 30 - BioSemi64 Coordinate Geometry (Approved as QC-15)

The active BDF loader assigns MNE's generic `standard_1005` coordinates. MNE
documents that template as the international 10-05 system and separately
provides `biosemi64` for the BioSemi 64-electrode cap. All 64 anatomical scalp
names happen to exist in both templates, so loading succeeds and the mismatch
is silent. BioSemi identifies its standard 64-channel cap as a 10/20 layout
and supports either anatomical 10/20 or ABC hardware labels.

This geometry is used by the experimental spatial-predictability score,
bad-channel cluster construction, and MNE spherical-spline interpolation. A
local MNE 1.9 comparison over the toolbox's 64 scalp labels found a median
coordinate-direction difference of 5.8 degrees and a maximum of 14.0 degrees.
With the active QC rules, 26 of 64 up-to-six-neighbor sets changed and the
cluster graph contained 204 rather than 197 edges. Therefore the choice can
change flags and interpolated values; it is not merely a display difference.

Recommended bounded correction: use `biosemi64` as the single active
processing/QC template, require all canonical scalp identities and finite
coordinates before spatial QC or interpolation, keep mastoid references and
CMS/DRL outside the scalp montage, version the geometry/cache identity, and
revalidate geometry-dependent experimental thresholds. Preserve the separate
locked Free Harmonic Clustering graph. If raw BDF headers use A1-A32/B1-B32
rather than anatomical names, require an explicit verified mapping instead of
guessing from channel order.

Sources: [MNE montage definitions](https://mne.tools/0.24/generated/mne.channels.make_standard_montage.html),
[MNE interpolation documentation](https://mne.tools/stable/generated/mne.io.Raw.html),
and [BioSemi headcap specifications](https://www.biosemi.com/headcap.htm).

**Decision:** accepted on 2026-09-03 as QC-15 and made execution priority 1.
Because most historical recordings required interpolation, treat prior
datasets as potentially affected rather than assuming the geometry difference
was harmless. Correct the active geometry, prevent old/new outputs from being
mixed silently, and perform the sensitivity and reprocessing assessment in the
same action. Anatomical headers can map directly; A/B hardware labels require
an explicit verified profile if encountered.

The user further decided that BioSemi ActiveTwo 64 is the sole supported
montage for now. Add a project settings entry that displays and persists this
choice, but offer no alternative montage until a future validated expansion.

### Item 31 - Independent Kurtosis Bad-Channel Rule (Approved as QC-16)

After filtering and downsampling, preprocessing calculates one kurtosis value
per remaining EEG channel, normalizes those values against a 10%-trimmed
across-channel distribution, and selects channels with absolute z above the
project threshold of 5. A selected channel is immediately added to the bad
list and interpolated; the report retains its name but not its kurtosis, signed
z, or supporting time evidence. QC-06 already changes its temporal input to
the analyzed samples, so this item concerns the threshold's authority.

This is an EEGLAB-inspired method with real precedent: EEGLAB offers normalized
kurtosis with a default five-standard-deviation channel threshold and 10%
trimming. The implementation is not numerically identical because its trimming
indices and population standard deviation differ. More importantly, kurtosis
can identify a peaky distribution but cannot by itself distinguish a failing
electrode from a transient physiological or movement artifact. Published
comparisons report weak kurtosis-only bad-channel detection relative to
multimetric methods; those datasets do not directly calibrate FPVS BioSemi64.

Recommended policy: retain kurtosis as separately identified evidence, but
make a kurtosis-only result review-only unless an independently validated
channel-health measure corroborates it. Require finite inputs/statistics and a
positive finite threshold, preserve raw kurtosis and signed z with analyzed
span/method provenance, and calibrate threshold and persistence on
representative FPVS BioSemi64 recordings before giving it sole automatic
interpolation authority. The formula contains no literal 6/1.2/120 assumption,
but its performance can still change with duration, sampling, filters, and
transient opportunities.

Sources: [EEGLAB `pop_rejchan`](https://github.com/sccn/eeglab/blob/develop/functions/popfunc/pop_rejchan.m),
[EEGLAB `rejkurt`](https://raw.githubusercontent.com/sccn/eeglab/develop/functions/sigprocfunc/rejkurt.m),
[PREP comparison](https://doi.org/10.3389/fninf.2015.00016), and
[Kumaravel et al. (2022)](https://doi.org/10.3390/s22197314).

**Decision:** accepted on 2026-09-03 as QC-16. A kurtosis finding corroborated
by another eligible independent method can trigger automatic interpolation. A
kurtosis-only finding requires an explicit GUI review before processing may
interpolate that channel. Preserve the accepted analyzed-interval scope and
continuous-Raw interpolation application.

### Item 32 - Frequency-QC Technical Scaffolding (No Action)

Preserve exact selected BCA-column validation, versioned analysis/decision
fingerprints, stale-output invalidation, separate automatic/manual provenance,
original workbooks, and full-audit visibility. Preserve the recording-scoped
backend identity for repeated sessions; QC-03 already owns its GUI correction.
The separate Stats outlier stage appropriately keeps finite statistical
outliers review-only and treats nonfinite inputs as technical failures.

**Disposition:** no action on these safeguards. The scientific authority of
summed-BCA magnitude thresholds remains Item 33.

### Item 33 - Summed-BCA Magnitude Authority (Approved as QC-17)

Frequency-domain QC currently flags absolute summed BCA above 10 uV, creates a
strong warning above 50 uV, automatically excludes an electrode above 250 uV,
and automatically excludes a recording/participant when at least 11 unique
electrodes cross 250 uV. One condition can therefore remove an electrode from
all conditions, and the GUI cannot reverse an automatic exclusion.

Summed baseline-corrected harmonic amplitude is a defensible FPVS outcome, but
no source or repository calibration supports these particular numbers as
automatic artifact decisions. The sum changes with the number and identity of
harmonics, so fixed uV thresholds do not have a stable meaning across rates,
harmonic lists/counts, selection profiles, usable spectral domains, or
durations. An extreme tagged response can
be artifact or real signal; dependent-variable magnitude alone cannot decide.

The rule is also circular: it calculates QC from a provisional harmonic list,
uses that result to change electrodes/cohort, and then selects the final
harmonics from the changed inputs. The final list can differ without the
exclusion being rescored against it, and the provisional settings builder omits
options honored by final selection.

Recommended policy: retain 10/50/250 uV and the electrode-count boundary only
as clearly labeled experimental review bands until protocol-wide calibration.
Summed-BCA magnitude alone never automatically excludes an electrode,
recording, or participant. Require an eligible independent artifact/technical
measure or an explicit GUI decision, scope the finding to its actual condition,
use identical settings for provisional/final calculation, and recompute and
recheck after reviewed exclusions before final acceptance.

Sources: [Retter et al. (2021)](https://doi.org/10.1162/jocn_a_01763) on
multiharmonic FPVS response measurement and
[Keil et al. (2022)](https://doi.org/10.1111/psyp.14052) on duration and
frequency-domain reporting.

**Decision:** accepted on 2026-09-03 as QC-17. Add a dedicated Experimental
settings section, retain the current magnitude/count values as editable rough
defaults, and make the screen review-only. Findings and decisions are scoped to
their recording, condition, and electrode. Recompute against the canonical
final harmonic list before accepting outputs. The review-only screen is On by
default and can be disabled; the independently riskier QC-04 removed-electrode
detector remains Off by default in the same section.

### Item 34 - FullFFT Grid Validation (No Additional Action)

Preserve the exact checks that the grid starts at zero, is uniform, and contains
one exact oddball target. Preserve explicit GUI decisions and original
workbooks. QC-12 already replaces the literal 1.2-Hz target with the project
rate; QC-13 makes the declared cycle count authoritative and retains cohort
majority only as a legacy/corruption fallback. No separate action is needed.

### Item 35 - Harmonic Profiles and Canonical Selection (No Action)

The four versioned harmonic profiles are analysis-method choices rather than an
artifact detector. Preserve their locked behavior, canonical selected list,
fingerprint, and stale-result guards. QC-12, QC-14, and QC-17 already own the
rate, neighboring-noise, and final-list implications.

### Item 36 - Stats Finite-DV Integrity and Absolute-Limit Flags (No Action)

The Stats outlier stage flags finite derived values above its absolute limit but
does not remove them. It requires exclusion only when a derived DV is nonfinite
and therefore cannot enter the model. Preserve that distinction; QC-10 should
prevent nonfinite source BCA from reaching this stage ordinarily.

### Item 37 - Separate Stats Cohort-Relative BCA Screen (Approved in QC-17)

Stats has a second BCA screen in addition to processing-end QC. For each
condition and mutable ROI, it calculates the sum of absolute harmonic means and
largest absolute harmonic, then compares participants using median/MAD with
warning/critical robust-score defaults of 6/10 and absolute floors of 5/10 uV
for the sum and 1/2 uV for the largest harmonic. It is currently review-only.

The relative comparison can be useful context, but its implementation rebuilds
all available default oddball harmonics instead of consuming the canonical
selected list, depends on mutable Stats ROIs, silently skips unreadable or
incomplete inputs, and is still presented as an exclusion system. It can
therefore disagree with QC-17 and is not rate- or protocol-agnostic.

Recommended policy: preserve the measurement as an optional cohort-relative
view inside QC-17's Experimental summed-BCA review. Use the project protocol,
canonical final harmonic list, explicit recording/condition/ROI scope, shared
fingerprints, and technical completeness statuses. Keep its 6/10 robust scores
and uV floors as labeled experimental defaults. Remove its independent
exclusion authority and duplicate review state.

**Decision:** accepted on 2026-09-03 as an expansion of QC-17. Show this evidence
in the actual QC-17 GUI review, retain it as experimental context, and have Stats
consume the saved project-level evidence and decision. If the user retains the
data, this screen does not change the modeled cohort or values. Any exclusion
requires an explicit decision and must propagate consistently downstream.

### Remaining Decision Inventory After Item 37

Five scientifically meaningful QC decision groups remained after Item 37:

1. Experimental removed-electrode detector calibration and exact numerical
   accuracy claims.
2. Condition-aware raw-spectral thresholds, classifications, and visibility of
   mains-notch/FPVS harmonic collisions.
3. Oddball marker schema and marker-train integrity, including duplicates,
   gaps, inferred codes, and continuation across anomalies.
4. Expected recording-by-condition completeness and current-run output
   authority, grouping missing conditions, failed processing/export, and stale
   or partial workbooks while preserving intentional exclusions.
5. Downstream electrode/ROI coverage after valid exclusions, including minimum
   membership and duplicate/unknown electrode handling.

The separate analysis-window temporal-processing investigation is not another
QC decision in this count. Per-file scan acknowledgement needs no separate
action beyond truthful QC-02 unavailable/failure states. Neutral FullFFT
provenance and sibling-step isolation remain covered by existing freshness and
technical-integrity safeguards.

### Item 38 - Experimental Detector Percentages (Approved in QC-04)

The current user text reports greater-than-99% specificity, approximately 60%
sensitivity, and 99.7% positive predictive value from the development lab's
data. The user chose to retain these values and may make the dataset public for
independent validation.

**Decision:** describe them specifically as internal validation on an in-lab
dataset, not universal or externally validated performance. Before release,
commit a reproducible calibration receipt containing sample denominators,
prevalence, confusion matrix, threshold-development/evaluation split, confidence
intervals, dataset and detector versions, and calculation code. Recalculate the
metrics after QC-01, QC-06, and QC-15 change evaluated windows and geometry;
display the reproduced values if they differ. A public dataset enables rather
than constitutes external validation.

Four decision groups now remain: raw-spectral screening, marker-train integrity,
recording-by-condition/current-output completeness, and downstream electrode/ROI
coverage.

### Item 39 - Preflight Scan Unavailable or Failed (No Additional Action)

Keep the existing explicit Continue/Cancel acknowledgement when a preflight file
cannot be scanned. Processing may still attempt the file, but the report must
state that preflight QC was not evaluated and preserve the technical reason.
Never translate an unavailable scan into a passing QC result. QC-02 already owns
the required outcome vocabulary, so no separate action module is needed.

### Item 40 - Condition-Aware Raw-Spectral Screen (Approved as QC-18)

The current condition-aware screen searches the raw analyzed spectrum for very
large, locally prominent narrow peaks. Its defaults require a legacy Hann
spectral score of at least 250, a local-mean ratio of 25, and a local
standardized score of 12. It then describes the peak as an expected FPVS
harmonic, within a planned notch band, a collision of those two, or an
unexpected frequency. Active condition-aware results are review-only, although
legacy widespread findings still reach a hard-exclusion compatibility path and
most classifications are hidden from ordinary GUI review.

This measurement can identify candidates worth inspecting, but the exact
thresholds have no demonstrated artifact-classification performance across
rates and durations. The local score is not a normal-theory z-test, scanning
many correlated bins changes its interpretation, and a fixed-bin neighborhood
spans a different physical bandwidth as duration changes. The existing Hann
`2/N` scale also omits coherent-gain normalization, so its number must not be
presented as a calibrated physical uV amplitude. A fixed 0.08-Hz harmonic
tolerance likewise represents different bin distances at different durations.

Notch/FPVS overlap is a separate deterministic processing conflict: a planned
notch can attenuate an expected response whether or not an observed raw peak
crosses the experimental thresholds. It must therefore be derived directly
from the canonical project target and notch grids and shown independently.

**Decision:** accepted on 2026-09-03 as QC-18. Put this project-owned screen in
Experimental settings, keep it On by default and review-only, retain the
250/25/12 values as provisional legacy-score defaults, classify expected peaks
from canonical FFT-bin identities, and expose unexpected findings and every
notch/FPVS collision by recording, condition, and occurrence. No current or
legacy spectral finding may automatically remove data. Calibration across the
supported protocol space is required before stronger claims or authority.

Item 47 later finalized the separate deterministic consequence: keep an
effective notch on overlap and mark only the affected standard frequency or
noise-based score unavailable. That rule does not turn the experimental screen
into participant- or condition-exclusion authority.

Three decision groups now remain: marker-train integrity,
recording-by-condition/current-output completeness, and downstream electrode/ROI
coverage.

### Item 41 - Project Oddball Code and Marker Integrity (Approved as QC-19)

FPVS Studio is not expected to create accidental duplicate oddball events as a
valid design. An extra event would more likely indicate malformed trigger
acquisition, code extraction, or an unexpected presentation record. The active
toolbox nevertheless treats every selected marker less than half of the fixed
1.2-Hz interval after the last retained marker as a duplicate and silently
ignores it. It also guesses whether oddballs use global code 55 or code
`50 + condition`: two observed condition-specific codes in one occurrence can
switch every occurrence of that condition without resolving mixed-code
ambiguity.

**Decision:** store one oddball marker code per project, with 55 as the
default. FPVS Studio imports its declared code; manual projects may change the
project value. Pass that same value through preflight, crop planning,
processing, fingerprints, and reports. Remove observed-count guessing from
current behavior. Existing projects or recordings that show evidence of a
non-55 or mixed legacy scheme require an explicit migration result rather than
a silent reinterpretation.

Unexpected extra markers are preserved as raw evidence and shown rather than
broadly discarded under the half-cycle heuristic. Only identical instances of
the same code at the exact same sample may be normalized, with that operation
reported. A missing marker or unexplained gap pauses its recording-condition
occurrence for GUI review. Full retention requires evidence that only the
trigger was lost while stimulation continued at the intended cadence and phase;
otherwise use a verified contiguous span satisfying QC-13 or exclude the
occurrence. No unresolved gap may be crossed automatically. QC-19 records the
execution details.

Two decision groups now remain: recording-by-condition/current-output
completeness and downstream electrode/ROI coverage.

### Item 42 - Recording-Condition Output Completeness (Approved as QC-20)

The current exporter can log a condition-level no-data, calculation, or write
failure and continue. A recording with some expected workbooks missing may
still be labeled completed, later QC may skip the absent input, and an older
file at the expected path may satisfy a file-existence check. That can make a
technical failure or stale result look like ordinary scientific missingness.

Requiring a workbook for every participant-condition would also be wrong.
Legitimate QC decisions, manual artifact review, unavailable acquisitions, or
occurrence-level exclusions can leave one participant without one condition
while other conditions remain usable.

**Decision:** accepted on 2026-09-03 as QC-20. Require every expected
recording-condition to be accounted for rather than workbook-present. A current
validated workbook is required for ready or partially retained cells; no
workbook is required for an explicitly excluded or unavailable cell with its
reason preserved. An unexplained absence, technical failure, stale file, or
invalid output blocks downstream frequency QC until corrected or resolved by a
separate explicit decision. Show exact occurrence counts, reasons, and
contributing sample sizes. An entirely empty declared group-condition cell
remains a hard analysis failure.

One decision group remains: downstream electrode/ROI coverage after valid
exclusions.

### Item 43 - Complete Fixed ROI Coverage (Approved as QC-21)

Stats currently normalizes electrode labels, takes whichever configured ROI
members remain in each workbook after exclusions, and averages them. A five-
electrode ROI can therefore use all five electrodes in one condition and only
one to four in another without a coverage warning. Duplicate ROI labels or
source rows can also weight one physical site more than once, while unknown
labels may be silently omitted. The resulting values do not necessarily
represent the same prespecified spatial measure.

This state should be rare because successful upstream interpolation restores
the full BioSemi64 scalp set. A successfully interpolated member remains part
of its ROI and is identified as reconstructed. A genuinely missing, duplicate,
unknown, or nonfinite source row is a technical integrity problem; a valid
explicit downstream electrode exclusion is a scientific missingness decision.

**Decision:** accepted on 2026-09-03 as QC-21. Require the complete project-
defined unique canonical electrode set for every primary ROI result. If a valid
condition-specific decision excludes one member, leave only that recording-
condition-ROI value unavailable; do not silently average a reduced set or
remove the member from other conditions. Reject invalid ROI definitions and
invalid source identities, preserve interpolation/exclusion provenance, and
report exact expected and used membership. Do not introduce a universal
partial-coverage percentage.

The fixed-electrode-set and whole-scalp-normalization decisions are recorded
in QC-21. The live 16.8-Hz default, generic ceiling, and duplicated target-list
paths are rejected; the filter-range +/-10-bin rule and shared resolver are
accepted. Effective notches remain active on base/oddball overlap, and affected
target/noise metrics are unavailable without excluding the whole condition.
The separate analysis-window temporal-processing
investigation remains open and does not authorize a method change.
