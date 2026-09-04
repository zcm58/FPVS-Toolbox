# QC-01: Five-Second Overlapping Transient Screening

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts when executing this action. Other action modules are unnecessary unless listed as dependencies below.


**Status:** design direction accepted; implementation and validation pending.

### Problem and Evidence

Condition-aware preflight currently examines every non-overlapping 10-second
block, including a final partial block. It already reads every sample in the
locked condition span. Shorter windows change the local prominence of a burst;
they do not fill sampling gaps in the current condition-aware scan.

For an ideal rectangular pulse of amplitude A occupying a fraction q = d/T of
a window, with negligible background noise, population SD is
`A * sqrt(q * (1 - q))`. A 50 ms pulse occupies 1%, 0.5%, or approximately
0.33% of 5-, 10-, or 15-second windows respectively. A 300 ms pulse occupies
6%, 3%, or 2%. These are illustrative calculations, not EEG validation results.

Shorter windows can increase burst-related SD, but the current rare-burst rule
also depends on compressed P2P99 and extreme-to-percentile ratios. Changing
window length can move a burst into the percentile range and remove that
classification. The high-amplitude branch may catch it instead, but this is
not guaranteed. Window geometry and transient thresholds must be evaluated
together rather than assuming that shorter always means more sensitive.

Overlap reduces boundary splitting: a burst at 4.9-5.1 seconds spans two
non-overlapping 5-second windows but fits inside the 2.5-7.5-second window.
Short local windows are established in EEG QC methods such as
[PREP](https://www.frontiersin.org/journals/neuroinformatics/articles/10.3389/fninf.2015.00016/full),
and overlapping windows appear in
[EEGLAB clean_rawdata](https://eeglab.org/plugins/clean_rawdata/Documentation.html).
These sources support the general approach; neither validates this toolbox's
5-second/50% choice or its thresholds.

### Recommended Solution

Use 5-second windows advancing by 2.5 seconds for supplementary transient
review. Keep exact full-condition metrics and the existing full-span FFT.
Calibrate the transient rules against labeled bursts and clean recordings,
using the present 10-second behavior as the reference. Retain 5- and 15-second
non-overlapping comparison arms to distinguish window-length effects from
overlap effects. Do not automatically delete time segments, interpolate a
channel, or reject a participant because of these transient findings.

### Implementation Shape

1. Separate unique condition data from diagnostic window views. Compute
   full-condition metrics once from the original float64 condition buffer.
   Do not concatenate overlapping windows or average their statistics to
   reconstruct the condition. Preserve full-condition classifications and
   across-occurrence persistence numerically.
2. Generate deterministic integer sample indices for the 5-second window and
   nominal 2.5-second hop. Record actual sample counts and durations so rounding
   at unusual sampling rates is explicit. Keep unique condition sample count
   separate from diagnostic-window count.
3. Use regular full windows, then append one full window ending at the exact
   condition end if needed; deduplicate an existing final window. This edge
   window can overlap more than 50%. For conditions shorter than 5 seconds,
   use one explicitly identified short window without padding or extending
   the analysis span. Include that case separately in threshold validation.
4. Read each condition once and slice views for overlapping windows. Decouple
   the current 10-second disk-read chunk from diagnostic window length;
   preserve condition-only memmap buffering, bounded concurrency, and
   cancellation/cleanup behavior.
5. Retain transient high-amplitude/rare-burst findings and quietest/highest
   window provenance. Keep isolated quiet windows out of removed-electrode
   suggestions. Separate any new transient-specific calibration values from
   persistent/full-condition and processing-runner thresholds.
6. Present repeated overlapping detections without counting them as independent
   events or additional bad channels. Retain underlying intervals; summarize
   their union when describing flagged time, explicitly as flagged-window
   coverage rather than measured artifact duration.
7. Version the changed preflight method and include window length, hop, tail
   policy, and transient calibration identity in cache/provenance. Old cached
   transient results must miss. A review-only change does not itself require
   changing continuous-processing fingerprints; reassess this if later approved
   items alter actual sample/channel inclusion.

### Owners and Dependencies

- `src/Main_App/processing/preflight_qc_plan.py`: policy constants/version.
- `src/Main_App/processing/preflight_qc.py`: condition buffering, window
  construction, orchestration, and cache-method identity.
- `src/Main_App/processing/raw_channel_qc.py`: exact aggregation, transient
  evaluation, persistence, and result provenance. Its current evaluator
  explicitly rejects overlap and reconstructs full conditions from blocks;
  merely relaxing the contiguity check is incorrect.
- `src/Main_App/processing/removed_electrode_detection.py`: calibration owner;
  keep any transient calibration change isolated from persistent rules.
- Relevant raw-channel/preflight tests under `tests/processing/`; GUI review
  and QC summary consumers only if needed to convey window provenance.

The existing
[condition-aware preflight speedup plan](../../active/condition-aware-preflight-qc-speedup.md)
specifies 10-second scoring windows. On implementation, QC-01 supersedes that
scoring-window decision only. Its exact-span, full-condition, review-only,
buffering, and concurrency constraints continue. Update the conflicting plan
text when implementation lands, keeping current-behavior documentation truthful
until then.

The processing runner separately samples six 10-second windows across the raw
file. QC-01 alone does not change that detector. The later accepted QC-06
supersedes its whole-recording sampling scope, and QC-04 defines the opt-in
control. Do not assume QC-01's transient thresholds validate persistent
channel inference under the changed sampling scope.

### Validation and Acceptance

- Deterministic geometry: cover every sample without going outside the locked
  span; verify exact multiples, irregular endings, a condition shorter than
  5 seconds, rounded sample sizes, and no duplicate final window.
- Numerical regression: exact full-condition metrics, persistence, and
  full-span spectral results match the existing implementation on identical
  inputs. RAM/memmap paths agree and inputs remain unchanged.
- Targeted synthetic checks: 50, 100, and 300 ms artifacts at varied amplitudes,
  polarities, background levels, and boundary positions. Verify independently
  calculated metrics and cases where percentile-rule classifications switch.
  Do not write a test asserting universal improvement from shorter windows.
- Empirical calibration: use independently annotated transient intervals and
  clean intervals, with plugged-in artifacts distinguished from physically
  removed electrodes. Split development and holdout sets by participant or
  recording, never by overlapping windows. Review-confirmed automatic flags
  alone are not independent ground truth.
- Report event recall, false alerts per recording and per clean recording hour,
  distinct channels flagged, and review burden. Stratify by available recording
  duration, presentation/oddball rate, and equipment. Account for correlated
  windows and participant-level uncertainty. Freeze acceptable recall and
  false-review burden before tuning/holdout scoring; do not invent universal
  accuracy claims from one lab's data.
- Record the chosen thresholds, dataset/label provenance, comparison results,
  and residual uncertainty. If labeled data are unavailable, keep empirical
  validation open; unit tests and simulations cannot close that requirement.
- Check cancellation, memmap cleanup, method/cache invalidation, and realistic
  scan cost. At 120 seconds, regular 5-second/50% windows produce 47 windows
  versus 12 disjoint 10-second blocks; this is about twice the sample visits,
  not a prediction of four times total runtime. No fixed 120-second requirement
  is introduced.

### Documentation and Verification at Implementation

Update `docs/agent/architecture/preprocessing-contract.md`, the existing
speedup plan, and
`docs/agent/quality/removed-electrode-detection-calibration.md`; update
`docs/user/reference/methods-reporting-checklist.md` and relevant QC help to
describe the accepted method and its calibration limits. No ownership or
architecture changes have occurred in this planning-only pass.

Run the processing focused gate first:

```console
python .agents/scripts/verify.py --scope processing --tier focused
```

Add only relevant GUI-static/project-I/O gates if those surfaces change. Qt
execution remains CI-only unless a safe visible environment is explicitly
authorized. Document a visible smoke path for transient timing, duplicate
presentation, persistent suggestions, and cancellation. Run
`python .agents/scripts/verify.py --scope repo --tier precommit` at the final
implementation handoff. Record results separately from empirical calibration.
