# QC-06: Score Signal-Based QC Only Within Analyzed Intervals

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** implemented on 2026-09-04. The user explicitly broadened the proposed
amplitude-only boundary to analysis and flagging generally. Implementation
uses one fingerprinted reviewed source plan, validates it against the current
protocol/event map before cache access, realizes the same bounds on the actual
post-resample grid, and reuses them for signal QC, kurtosis, and epoch creation.
Calls without analyzed-interval context return `not_evaluated`; they do not run
legacy whole-file or first-90-second scoring. The user requested item 15's
separate investigation of processing scope and explicitly confirmed
analyzed-period bad-channel decisions with no change to interpolation
application. Filtering/resampling context remains under investigation.

### Problem and Accepted Scope

Normal V3 preflight already scores each occurrence's exact locked analysis
span. The runner's six distributed 10-second windows can include setup and
breaks and feed amplitude, low-variance, high-amplitude, rare-burst, and spatial
metrics (`raw_channel_qc.py`, around lines 709 and 1036-1250). Automatic
candidate-count, hemisphere, and cluster rules inherit those inputs. The
compatibility preflight path also uses that sampler and a spectral scan of up
to the first 90 seconds (`preflight_qc.py`, around line 1464;
`raw_spectral_qc.py`, around line 220).

Preprocessing kurtosis reads all retained continuous EEG samples after
filtering/downsampling (`preprocess.py`, around lines 837-866). An artifact in
a break can therefore affect which electrodes are interpolated. The accepted
boundary must cover this scoring step too.

Post-processing FFT/BCA QC already consumes exports of cropped condition
epochs (`post_process.py`, around line 575). No additional interval restriction
is needed at that direct input boundary; its other scientific issues remain
open. Manual electrode lists and geometry checks on confirmed manual channels
are not temporal measurements. Header integrity and event discovery can still
inspect the file information needed to locate the analysis spans.

### Implementation Shape

1. Share one authoritative definition of the selected, retained condition
   occurrences and exact analysis bounds across preflight, processing QC,
   kurtosis, and epoch export. Preserve the shared locked crop and shortest
   common repetition rules. Exclude setup, breaks, discarded tails, and
   unselected intervals; do not substitute a fixed 120-second interval.
2. Represent source-rate and realized downsampled sample coordinates explicitly,
   including sample origin, condition/occurrence identity, and selection
   provenance. Resolve the target-grid plan after downsampling and before
   kurtosis, then reuse it for final epoch construction. Reconcile earlier
   raw/preflight spans with that plan; do not assume independently rounded
   times or rescaled indices produce the same retained samples. Document
   expected grid-rounding differences between corresponding time intervals.
   Treat a missing/invalid plan or unexplained mismatch as a planning failure, not
   permission to fall back to whole-file or first-90-second scoring.
3. Measure general raw amplitude within each analyzed occurrence. Retain its
   paired STD/P2P99 values, interval, and reason through preflight and processing.
   Restrict all experimental signal-derived candidates to those same analyzed
   intervals and honor QC-04's effective opt-in state. Restrict active
   compatibility routes too. QC-01's local windows must stay inside an
   occurrence; never bridge a break or duplicate overlapping samples in
   full-span metrics.
4. Compute each channel's existing kurtosis statistic over the union of the
   retained samples, before repetition averaging. Count each sample once and
   preserve sample weighting, existing across-channel normalization, and the
   configured threshold for this scope change. Gathering values for this
   distributional statistic is permissible; joining conditions into a new
   continuous signal before filtering is not part of this action. Keep
   kurtosis at its present pipeline position and apply interpolation and
   final referencing to the resident continuous Raw in the current order.
   The user explicitly accepted leaving interpolation application unchanged;
   do not add interval-only repair or different repair maps per occurrence.
5. Record scoring-span and method identity in preflight results, preprocessed
   Raw cache metadata, the processing ledger fingerprint, and downstream
   processing provenance. This broader change can affect interpolation and
   final EEG, so a preflight-cache-only version change is insufficient.
   A changed analysis-span selection requires recomputing affected scores;
   never present whole-recording cached decisions as interval-scoped results.
   Preserve historical outputs and confirmed manual decisions. Later cohort
   exclusions alone must not silently rewrite time spans or reprocess EEG.
   Bind cache lookup to the current canonical project protocol and condition
   event map as well as the reviewed source-span fingerprint. Validate that
   context before cache lookup. A caller without the project root and event map
   must receive an explicit `not_evaluated` planning result rather than legacy
   whole-file or first-90-second signal QC.
6. Pool each channel's unique retained samples as specified in item 4, so
   longer retained spans contribute more samples; do not equal-weight
   conditions. Treat this kurtosis result as recording-wide evidence over the
   retained union. It can corroborate only a scope-matched persistent method
   under QC-16; an occurrence-only detector finding cannot corroborate it.
   QC-04, QC-08, QC-09, and QC-16 own detector persistence, thresholds, and
   action authority. Recalibrate affected thresholds on this sampling domain;
   estimates from the old six-window lab calibration do not automatically
   transfer. QC-05 amplitude severity and QC-01 transients remain review-only.

### Validation, Dependencies, and Documentation

- At each QC scoring input stage, hold the analyzed samples fixed and vary only
  outside samples: direct metrics, flags, and channel decisions must be
  unchanged. This is not an end-to-end claim that changing raw data outside
  the crop has no effect after continuous filtering; item 15's investigation
  addresses the appropriate preprocessing context.
- Put comparable artifacts inside and outside selected spans, including
  setup/breaks, tails, multiple repetitions, and unselected conditions. Verify
  sensitivity to inside artifacts with independently calculated metrics.
- Verify exact bounds and unique sample counts across source/target sampling
  rates, nonzero sample origins, irregular durations, and repetition alignment.
  Preserve RAM/memmap parity, bounded memory, cancellation, and actual epoch
  identity. Verify no whole-file compatibility fallback or stale cache reuse.
- Preserve the numerical order and existing kurtosis mathematics apart from
  its sample selection. Demonstrate that interpolation targets can change
  when an outside artifact previously influenced kurtosis, and carry truthful
  interpolation outcomes into QC-02. Empirical detector calibration remains
  a separate required evaluation, not something unit tests establish.

Primary owners are `preflight_qc_plan.py`, `preflight_qc.py`,
`raw_channel_qc.py`, `raw_spectral_qc.py`, and `preprocess.py` under
`src/Main_App/processing/`, plus `src/Main_App/Performance/process_runner.py`
and the existing cache/ledger/provenance owners. Reuse the public preprocessing
surface and shared crop helpers; avoid an alternate processing pipeline.

Implement the shared span/provenance work before finalizing QC-01/QC-05
calibration. Run the processing focused gate and relevant project-I/O/static
GUI checks through the repository driver; GUI execution remains CI-only.
Update `docs/agent/architecture/preprocessing-contract.md`,
`docs/agent/architecture/fft-crop-method.md`, the calibration guide, the active
condition-aware preflight plan, and
`docs/user/reference/methods-reporting-checklist.md` when implementation lands.
Update the post-processing export contract where shared span provenance changes.
The scoring-sample change is explicitly authorized; operation-order and
harmonic-selection guards remain intact and must receive focused regression
coverage. Current-behavior architecture docs remain unchanged during planning.
