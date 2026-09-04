# Analysis-Window Scope of Preprocessing: Scientific Investigation

## Status and Authorization

Opened 2026-09-03 at the user's request. This is an execution plan for an
evidence-led investigation, with initial code and literature findings below.
The full investigation and numerical comparisons have not been executed.
After reviewing the initial evidence, the user explicitly decided to restrict
bad-channel decisions to analyzed periods and leave interpolation application
unchanged. That scoring change is owned by QC-06. This investigation now
focuses on temporal filtering/resampling and analysis boundaries; it does not
authorize a new processing method, settings change, or source edit.

This plan reopens item 15 of the
[QC scientific review](qc-scientific-and-protocol-flexibility.md). QC-06's
accepted direction to restrict direct signal-based QC scoring to analyzed
intervals remains recorded. Continuous-Raw interpolation application is now
closed with no action. QC item 16 subsequently closed with no additional
montage-correction or blocking/failure-policy changes for current BioSemi64
support. Keep the independent temporal-processing investigation open; resume
the main QC plan at its current manual-review checkpoint.

## Objective and Decision to Produce

Determine for every active processing step whether its measurement inputs,
parameter-estimation inputs, transformation inputs, and retained outputs have
appropriate temporal scope. Explain the scientific rationale, published
precedent, and limitations for each. Conclude with an evidence-based
recommendation per step: retain, improve scope/provenance, or propose a
specified method change. Do not assume all operations should share one scope.
Retain the settled spatial-interpolation findings as the rationale for no
change; do not require another comparison or approval of that same decision.

Evaluate projects with different presentation rates, oddball rates, condition
lengths, repetition counts, and sampling rates. Defaults of 6 Hz, 1.2 Hz,
120 seconds, and 256 Hz must not become validity assumptions. Separate
scientific comparisons from present software limitations on supported rates.

## Accepted Decision and Supporting Assessment

**User decision, 2026-09-03:** use only analyzed samples for bad-channel
decisions; preserve the current interpolation algorithm, application across
continuous Raw, and pipeline position. No interval-only interpolation writes
or condition-specific repair maps are part of this work. QC item 16 leaves
existing failure handling unchanged; QC-02 still corrects outcome reporting.

Three distinct decisions can be described as "limit interpolation to analyzed
periods":

1. **Choose bad channels using analyzed samples.** This addresses the current
   whole-recording kurtosis and runner sampling problem: setup/break activity
   can change an interpolation decision even when the analyzed signal is
   otherwise adequate. QC-06 covers this accepted scoring boundary. Evaluate
   indirect temporal-filter influence separately; a scoring mask is not proof
   that outside activity cannot affect processed values.
2. **Apply an already fixed channel repair only to analyzed samples.** The
   current EEG interpolation is spatial: it reconstructs a bad electrode from
   donor electrodes at the same time point. With the same processed input,
   bad/donor channels, geometry, origin, and interpolation settings, applying
   that repair to additional discarded times does not change the retained
   samples. There is no established scientific benefit from merely avoiding
   repair of data that will be discarded.
3. **Choose different bad channels or repair maps in different periods.** This
   is a substantive alternative. It can preserve a genuinely good channel in
   periods where it works, but changes spatial reconstruction across periods.
   Its effect on reference values, scalp patterns, variance, FPVS harmonics,
   and condition contrasts requires evaluation. Trial-specific repair has
   published precedent; it is neither automatically superior nor inherently
   invalid. Do not conflate it with simply cropping a fixed repair. This
   alternative is outside the accepted implementation and is not a required
   work package; reconsider it only if the user separately reopens it.

The code basis for point 2 is installed MNE **1.9.0**,
`.venv/Lib/site-packages/mne/channels/interpolation.py`: lines 62-118 construct
the matrix from channel positions; lines 121-129 multiply it by the good
channel data; lines 164-169 connect the two. The toolbox calls this through
`Raw.interpolate_bads` after temporal filtering and resampling. The loader
supplies template electrode geometry; interpolation accuracy also depends on
that geometry and adequate donor channels, independently of time-window scope.

For channel-by-time data X, fixed spatial map M, and time-column selection P,
`(M X) P = M (X P)`. This is an algebraic inference from the implementation,
not an empirical validation result. A subsequent fixed average-reference map
also acts independently at each time. Equivalence does not cover changing
channel decisions, donor sets, montage, filters, event alignment, bad-channel
metadata, or later time-mixing operations. Verify those conditions explicitly.
Do not reorder filtering and interpolation based on this identity.

**Accepted disposition:** restrict bad-channel scoring as specified in QC-06
and retain interpolation application. The algebra and inspected implementation
support that distinction; no numerical equivalence experiment is required to
reopen the settled application question. Continue the investigation of temporal
filtering/resampling, outside-artifact influence, and boundary handling. Retain
their existing behavior until evidence and a specific future change have been
reviewed.

## Current Toolbox Scope: Initial Code Inventory

Line references describe the code inspected on 2026-09-03; recheck them during
execution. Most processing owners below are under `src/Main_App/processing/`.

| Step | Current temporal scope | Consequence to investigate |
| --- | --- | --- |
| Header validation and event discovery | Recording/file metadata and event stream | Locating analysis intervals requires information outside those intervals; this is not signal-quality scoring. |
| Normal V3 preflight raw/transient/spectral QC | Shared locked condition-occurrence spans (`preflight_qc_plan.py:109`, `preflight_qc.py:1215`) | Already condition-based. Verify the selection/exclusion map and target-rate correspondence, not only the span formula. QC-01 changes local scoring-window geometry. |
| Runner raw-channel inference and amplitude | Six distributed 10-second windows (`raw_channel_qc.py:709`, `process_runner.py:1268`) | Outside samples can influence candidates and derived burden checks. QC-06 changes this measurement domain. |
| Compatibility preflight | Same sampler plus up to the first 90 seconds for spectra (`preflight_qc.py:1464`, `raw_spectral_qc.py:220`) | Confirm active callers; remove out-of-span fallback from supported QC paths under QC-06. |
| Initial selected-pair reference | Continuous Raw, before filtering (`preprocess.py:385`) | Spatial subtraction at each time; selected reference channels and failure state matter, not a temporal mean of the recording. |
| Drop references and optional channel limit | Entire channel set (`preprocess.py:431`, `:500`) | Channel selection has no independent time-window calculation; preserve stim and montage identities. |
| FIR band-pass | Continuous spans separated by recognized `edge` annotations (`preprocess.py:601`) | Temporal mixing can carry outside artifacts into retained samples; condition markers do not by themselves define filter boundaries. |
| Optional FFT multi-notch | Each complete recognized edge-delimited segment (`fft_multinotch.py:190`, `:314`) | FFT/IFFT uses the segment's data and grid. Its influence can extend beyond nearby crop edges; validate separately from FIR. |
| Downsampling | Continuous Raw (`preprocess.py:767`) | Temporal anti-alias processing and event-grid changes. Establish actual segmentation and padding behavior in the installed runtime. |
| Kurtosis-based bad-channel selection | All retained continuous EEG samples after filtering/downsampling (`preprocess.py:860`) | Break/setup samples can determine interpolation. QC-06 restricts scoring; pooling and calibration need explicit justification. |
| Spherical interpolation | Continuous Raw, one current bad-channel set (`preprocess.py:947`, `:996`) | User accepted no change to application. Restrict upstream bad-channel scoring under QC-06; no interval-only writes or occurrence-specific maps. |
| Final average reference | Continuous Raw after interpolation (`preprocess.py:1037`) | Spatial, pointwise in time. Changing successful repair or contributing-channel state can alter every retained EEG channel. |
| Final epoch extraction and repetition averaging | Shared locked retained spans, then signed samplewise averaging (`process_runner.py:1572`, `:1724`; `Shared/post_process.py:575`) | Preserve exact grids and repetition identities; determine which configured or excluded conditions actually reach each earlier step. |
| FFT/BCA, harmonics, and frequency-domain QC | Cropped/averaged exports | Direct inputs are interval-based; effects of earlier filtering, interpolation, and sample selection remain in those inputs. No harmonic-method change is authorized. |

Known participant-condition and recording-condition exclusions currently remain
downstream-only (`processing_ledger.py:34`); the runner still loops over the
configured event map (`process_runner.py:1562`). They must not silently become
upstream preprocessing selections. The preprocessed-Raw cache settings payload
currently omits the event map and scoring spans (`process_runner.py:620`).
If those inputs begin controlling channel decisions, both Raw-cache and ledger
identities need reconciliation. Define which decisions are frozen before a run
and which later exclusions change only the analyzed cohort, to avoid a
selection/reprocessing feedback loop.

FIR length is scaled from 8,449 taps at the target rate to preserve duration
(`preprocess.py:83`, `:544`). At 256 Hz this is approximately 33 seconds of
kernel span, not a 5-second transient window. The `zero-double` application,
padding, and downstream transforms determine effective temporal influence;
measure the composed response rather than choosing a guard interval from this
single number. QC-01's 5-second/50% windows are diagnostic windows, not a
filter length, new crop, or interpolation schedule.

## Evidence Register and Limits

Use primary research to establish published practice, official software
documentation to establish documented behavior, and local code to establish
what this toolbox actually does. None alone proves optimal performance for
this lab or for different protocols. Initial sources:

| Source | Relevant evidence | Limit on the conclusion |
| --- | --- | --- |
| [Volfart et al. (2021), DOI 10.1016/j.neuroimage.2021.118228](https://doi.org/10.1016/j.neuroimage.2021.118228), methods 2.4 | Describes initial trigger-based segmentation with additional pretrial data, interpolation and average referencing, followed by a further crop for final integer-cycle frequency analysis. | Precedent for repair on epochs broader than the final FFT interval. It does not establish continuous-file interpolation, the exact detection domain, trial-specific masks, or superiority over alternatives. |
| [Poncet et al. (2019), methods 2.5-2.6](https://15138e68bf.clvaw-cdnwnd.com/1caef9d353414e8be4f34c4530c14df0/200001944-5b24e5c251/Poncet2019.pdf), DOI 10.1016/j.neuropsychologia.2019.03.006 | Describes interpolation on 35-second sequence segments with margins, then a final 30-second FFT epoch. | A second explicit FPVS precedent for different repair and final analysis intervals; no comparative validation or explicit trial-varying mask policy. |
| [PREP, Bigdely-Shamlo et al. (2015)](https://www.frontiersin.org/journals/neuroinformatics/articles/10.3389/fninf.2015.00016/full) | Describes bad-channel detection, robust referencing, and interpolation, including recording-wide replacement of channels classified unusable. | Supports a global repair strategy within its own pipeline; not validation of the toolbox's kurtosis, lab thresholds, or every segment of a recording. |
| [Autoreject, Jas et al. (2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7243972/) | Describes cross-validated artifact rejection and local sensor repair within individual trials. | Establishes trial-specific repair precedent. It does not establish that changing maps by long FPVS condition or by 5-second QC window is appropriate here. |
| [MNE: handling bad channels](https://mne.tools/stable/auto_tutorials/preprocessing/15_handling_bad_channels.html#how-interpolation-works) | Explains EEG spherical-spline interpolation and availability on Raw and Epochs. | Official algorithm documentation, not a comparative clinical or FPVS validation. Live docs may differ from installed MNE 1.9.0; verify implementation. |
| [EEGLAB: filtering](https://eeglab.org/tutorials/05_Preprocess/Filtering.html) | Recommends continuous-data filtering to reduce epoch-edge artifacts; also explains why major artifacts may warrant removal with boundaries before filtering. | Challenges both "always crop first" and "outside activity never matters." It does not select this toolbox's boundary/padding policy. |
| [MNE: filtering and resampling](https://mne.tools/stable/auto_tutorials/preprocessing/30_filtering_resampling.html#resampling) | Discusses temporal filtering, epoch-edge artifacts, event-timing precision, and anti-alias tradeoffs. | An implementation/practice reference; do not adopt a new resampling recipe without validating the locked crop and rate constraints. |

Volfart's publisher methods were recoverable through indexed publisher text;
direct publisher retrieval returned HTTP 403 during this planning pass.
An alternative manuscript is [available in PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7613186/);
automated retrieval can encounter an access challenge. Archive a verifiable
accessible full-text method excerpt/reference during the
investigation before making a detailed replication claim. Distinguish this
paper from the Hauk et al. 2021 EEG/MEG paper with Volfart as coauthor
(DOI ending 118460). A repo statement of alignment with Volfart is not proof
that every preprocessing detail reproduces that paper. Volfart and Poncet
describe linear interpolation; the current toolbox uses MNE spherical splines.
Their timing precedent does not validate the toolbox's exact interpolation
algorithm. Likewise, "Autoreject global" refers to a shared rejection
threshold, not recording-wide channel interpolation.

## Execution Work Packages

### W1: Complete the Scope and Provenance Trace

- Complete the matrix for actual active callers, selected/excluded conditions,
  repetitions, caches, annotation boundaries, and exception paths. Distinguish
  mandatory input-validity checks from optional signal-quality scoring; do not
  suppress a nonfinite-data failure merely because it occurs outside a crop
  that a temporal transform still depends on.
- Record source and target sample coordinates, first-sample offsets, shared
  crop identity, donor/target channels, montage, reference, and processing
  versions. Resolve planned-versus-realized intervals without silently
  rounding them into agreement. Changing cohort membership alone is not
  permission to rewrite previous preprocessing.
- Preserve current continuous interpolation and its repair history; coordinate
  truthful outcome provenance with QC-02 and QC item 16. Partially repaired
  continuous objects and interval-aware interpolation metadata are unnecessary
  under the accepted no-change decision.

### W2: Complete the Scientific Comparison

- Extract exact detection, interpolation, referencing, filtering, epoching,
  and final-crop order from the original FPVS methods and relevant supplements.
  Mark unreported choices as unknown; retain contradictory precedents.
- Evaluate how temporal preprocessing and the accepted scoring domain behave
  for permanent channel failure, condition-limited failure, and a brief
  artifact. Keep the application method fixed. Validate detection separately
  under QC-06; do not assume interpolation can repair widespread corruption.
- Explain effects on reference, spatial resolution, retained measured data,
  condition comparability, and frequency-domain outcomes. Separate algebraic
  predictions from demonstrated numerical or empirical effects.

### W3: Targeted, Reproducible Numerical Investigation

Design non-GUI probes before running them, with frozen inputs and criteria.
Use synthetic signals with known clean counterparts first. Add labeled lab
recordings only when suitable labels and a representative dataset are available.
Keep data/output paths inside the active project or an explicitly designated
repository diagnostics output area. Never modify original recordings.

1. Hold analyzed raw samples fixed while varying outside impulses, drifts,
   clipping, and line noise. Run FIR, optional multi-notch, and resampling
   separately and composed. Measure change inside the retained interval versus
   artifact distance, amplitude, annotation boundaries, padding, and duration.
   Distinguish outside contamination from the new edge distortion caused by
   isolating a short interval. Do not require impossible zero influence from
   the current continuous temporal transforms.
2. Compare current continuous processing with explicitly specified alternatives
   using suitable context, guarded intervals, or independent segments. Preserve
   operation order within each candidate. Never concatenate separate conditions
   into an artificial continuous trace. Do not choose arbitrary padding or
   silently discard additional cycles to make a candidate appear better.
3. Coordinate QC-06's comparison of global versus analyzed-union scoring using
   known clean signal truth, keeping interpolation application fixed. Measure
   repair error, false repairs, retained good measurements, scalp-pattern and
   reference changes, harmonic amplitude/phase, BCA, and condition contrasts.
   Include intermittent failure, many adjacent bad electrodes, and corrupted
   donor channels. A transient flag alone does not justify permanent repair.
4. Cover on-grid alternative presentation/oddball rates, unequal durations and
   repetitions, short windows, and sample-rate conversions; report unsupported
   configurations as software limitations. Use participant/recording holdouts
   for empirical comparisons. Do not tune against a favorable final effect.

Define meaningful spectral/time-domain tolerances and acceptable repair/error
burdens before evaluating candidates. Do not invent a universal numerical
acceptance threshold without a design rationale. Report cases where a proposed
change makes results worse, and identify unavailable empirical evidence.

### W4: Decision Report and Integration

- Produce a concise, section-per-step report: current scope, evidence, counter-
  argument, result, recommendation, and remaining uncertainty. Explicitly answer
  which interpretations of the user's interpolation intuition are supported.
- Return a decision ledger identifying no-action findings versus specific
  implementation proposals. If implementation is warranted, extend QC-06 or
  add a separate approved action with cache migration, provenance, numerical
  acceptance criteria, and user-facing methods wording.
- Resolve this investigation before finalizing filter/resampling boundary
  decisions affecting QC-06. Interpolation application is already settled.
  This plan does not grant permission to start source edits before the overall
  QC review is finished.

## Constraints, Verification, and Completion

Keep the current operation order, FIR duration scaling, fingerprints, shared
crop, and versioned harmonic contracts intact during investigation. Any later
method change needs an explicit reviewed decision, appropriate cache/version
updates, and focused coverage. Use public processing APIs; no retired runtime
packages, `src/Standalone_Scripts/**`, local Qt/offscreen execution, or GUI
thread workarounds.

For future diagnostic/code changes, run
`python .agents/scripts/verify.py --scope processing --tier focused` first and
only additional relevant scopes. Run the repository precommit gate at an
implementation handoff. Software checks do not replace empirical validation.
Update the preprocessing contract, FFT-crop method, calibration guidance,
post-processing export contract where applicable, and user methods-reporting
checklist if behavior changes. Current architecture docs remain truthful to
unchanged behavior during this planning pass.

- [x] Capture the user's investigation request and reopen QC item 15.
- [x] Seed the scope matrix and evidence-based challenge to a blanket rule.
- [x] Record the user's accepted scoring boundary and no change to interpolation
  application; remove alternative repair maps and application-only experiments
  from required work.
- [ ] Complete W1-W2 with verifiable methods provenance.
- [ ] Freeze W3 inputs, alternatives, and comparison criteria; run the probes.
- [ ] Complete empirical work or explicitly identify the evidence still missing.
- [ ] Deliver W4 recommendations and record decisions before implementation.
