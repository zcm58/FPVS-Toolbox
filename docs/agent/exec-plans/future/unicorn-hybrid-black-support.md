# Unicorn Hybrid Black Support

Status: Planned

Created: 2026-09-25. This document records the user's requested implementation
plan; it does not authorize implementation in the plan-writing task or claim
that Unicorn recordings currently work in FPVS Toolbox. Keep this file in
`future/` until implementation is explicitly started, then move it to `active/`
and update the execution-plan index. All implementation phases below are pending.

Companion plan: FPVS-Studio-2.0 repository,
`docs/exec-plans/planned/unicorn-hybrid-black-support.md`.

## Objective and Fixed Decisions

Support the user's existing Unicorn Hybrid Black through this workflow:
FPVS Studio sends local UDP event codes to the vendor Recorder; the Recorder
writes raw BDF+; Toolbox imports that recording through an explicit Unicorn
profile and reuses its reviewed condition, FFT, BCA, SNR, and export workflow.
BioSemi acquisition and all existing BioSemi results must remain unchanged.

The user has fixed these boundaries:

- No new purchases, paid SDK/API, extra amplifier, trigger box, or equipment.
  Use the existing headset, computer, and available vendor Recorder. Do not make
  implementation depend on access to a paid programming interface.
- Raw BDF+ is the initial supported input. Processed Recorder output is not a
  substitute for raw EEG. CSV, XDF/LSL, a direct headset SDK, and a generalized
  acquisition framework are separate future scopes, not requirements here.
- The eight electrode positions are Fz, C3, Cz, C4, Pz, PO7, Oz, and PO8.
  Verify their recorded-label mapping explicitly; channel number alone is not
  evidence of electrode position.
- Keep Unicorn data at native 250 Hz throughout analysis. No downsampling,
  upsampling, resampling, or time-grid regularization is permitted. Fail on an
  incompatible sampling grid instead of changing it.
- Disable EEG interpolation for Unicorn, including automatic, manual,
  recording-wide, and condition-specific repair routes. Missing channels or
  samples must never be zero-filled or reconstructed to resemble BioSemi64.
- Preserve the core FFT/BCA/SNR arithmetic, neighboring-noise definitions,
  protocol-owned harmonic rules, repeated-measures identities, and export
  contracts. Device differences must remain visible in provenance.
- Local UDP connects Studio to Recorder on the same computer; the headset's
  Bluetooth EEG link is a separate path. Software send time is not proof of
  recorded-sample alignment or physical stimulus onset.

## Evidence and Existing Owners

The investigation inspected branch `codex/v3-release`, commit
`6de199039649173e085eeb059d699981ccecd617`, with pre-existing uncommitted QC,
settings, documentation, and test work. Preserve that work. Line references
describe the inspected working tree and must be rechecked during implementation.

The vendor's [Recorder manual](https://github.com/unicorn-bi/Unicorn-Recorder-Hybrid-Black/blob/main/README.md)
documents a raw BDF+ logger, EEG in microvolts, STATUS trigger values, and
optional counter, validity, battery, and timing signals. It also documents UDP
trigger reception. This supports the proposed route, but does not establish
the installed Recorder version's exact header, timing behavior, or data-loss
semantics. Those require fixtures from the user's existing installation.

| Current owner | Verified behavior and planned implication |
| --- | --- |
| `src/Main_App/io/load_utils.py`; `src/Main_App/Shared/load_utils.py:609` | Public loading API delegates to the shared owner. Full and lazy preflight reads currently require BioSemi headers before `mne.io.read_raw_bdf`. Add a narrow, explicit profile branch before that validation; keep one canonical loading surface. |
| `src/Main_App/io/eeg_geometry.py`; `src/Main_App/Shared/eeg_geometry.py:361` | BioSemi validates exactly 64 scalp signals, two recorded EXG references, stimulus, and supported auxiliaries. Keep this validator strict and separate from Unicorn validation. |
| `src/Main_App/projects/preprocessing_settings.py:142` | Current montage, references, and default downsampling settings are BioSemi-oriented. Persist explicit Unicorn acquisition, reference, native-rate, and repair-disabled policy without changing legacy defaults. |
| `src/Main_App/processing/preprocess.py:1129` | Initial EXG-pair reference, channel removal, and final average reference are existing BioSemi behavior. Do not route Unicorn through a missing-reference warning or synthesize EXG signals. |
| `src/Main_App/processing/preprocess.py:432`, `:1373`, `:1540` | FIR duration scaling, zero-double Hamming FIR, and filter-before-downsample order are locked. Current code only resamples when source rate exceeds target. Unicorn must explicitly disable all sample-rate changes rather than rely on 250 being below 256. |
| `src/Main_App/Performance/process_runner.py:213`, `:1896`, `:2256` | Source and processed events are compared with reviewed analysis spans. Event discovery currently includes an annotation fallback; Unicorn must use an explicit tested STATUS decoder without guessed annotation numbering. |
| `src/Main_App/projects/frequency_protocol.py:769`; `src/Main_App/Shared/fft_crop_utils.py:48` | Exact protocol cycles must produce integral samples and an on-bin FFT span. Reuse these rules at 250 Hz. |
| `src/Main_App/Shared/post_process.py:1040`; `src/Tools/Stats/analysis/noise_utils.py:84` | Common EEG values are converted from volts to microvolts before FFT. Preserve scaling and all existing metric formulas; prevent double conversion of vendor units. |
| `src/Main_App/processing/kurtosis_qc.py:46`, `:692` | Normalized-kurtosis reference requires 16 finite channels. It is unavailable for eight-channel Unicorn; do not lower its threshold or report an unavailable result as a pass. |
| `src/Main_App/Shared/roi_presets.py:21`; `src/Main_App/processing/roi_settings.py:122`; `src/Main_App/processing/roi_coverage.py` | LOT/ROT presets and frozen ROI identities are BioSemi-specific. Add explicit Unicorn definitions and geometry identities, not intersections with existing presets. |
| `src/Main_App/Performance/process_runner.py:993`; `src/Main_App/processing/full_fft_provenance.py:414`; `src/Main_App/processing/processing_ledger.py` | Cache, ledger, and FullFFT provenance encode BioSemi geometry. Profile identity must propagate through all affected validation and reuse boundaries. |
| `src/Main_App/gui/processing_inputs.py:866`; `src/Main_App/projects/grouping.py:260`; `src/Main_App/projects/raw_identity.py:19` | Registered-source selection and identity already accept `.bdf`; retain project boundaries and canonical participant/recording registration. Update BioSemi-only captions where necessary. |
| `src/Main_App/projects/dataset_index.py`; `src/Main_App/projects/fpvs_config_import.py` | Reuse canonical dataset identities and the existing Studio project-shell import. Do not infer new associations from file prefixes or create parallel group/participant logic. |

Follow the [loading contract](../../architecture/eeg-loading-contract.md),
[preprocessing contract](../../architecture/preprocessing-contract.md),
[FFT contract](../../architecture/fft-crop-method.md), and
[project I/O contract](../../architecture/project-io.md). The existing
BioSemi scientific decisions remain authoritative for BioSemi. This plan adds
an explicitly identified device policy; it does not reopen unrelated temporal
preprocessing investigations or restore retired source-localization packages.

## Input, Timing, and Provenance Contracts

### Device and recording identity

Use one versioned Unicorn acquisition profile with its own montage, source-label
mapping, coordinate source/version, reference policy, sample-rate policy, and
supported capabilities. Choose the smallest representation in the current
project/settings owners; a plugin registry or general device framework is not
required. A missing profile in an existing project must retain the exact current
BioSemi interpretation, serialization, and scientific fingerprint behavior.

Freeze the physical-to-recorded mapping from a fixture. Preserve source channel
order; normalize labels only through that explicit mapping. Physical REF/GND
electrodes are not additional EEG signals unless the file actually records
them. Keep STATUS as stimulus and supported telemetry as auxiliary data, never
as scalp EEG, average-reference members, ROIs, or harmonic-selection electrodes.

The common processing boundary remains MNE Raw with EEG in volts, native
250 Hz, validated channel geometry, recorded integer marker samples, and
separate source-integrity evidence. Validate BDF physical/digital ranges and
reader scaling against a known input before choosing any conversion. Do not
multiply EEG already converted to volts by another microvolt scale factor.

### Continuity and raw evidence

Before filtering, inspect the installed Recorder's actual counter, validation,
timing, and discontinuity representation. Establish counter wrap/reset rules,
the meaning of validity values, and whether timing describes host receipt or
acquisition. Treat absent or uninterpretable evidence as unknown, not as proof
of continuity. Do not assume a regular BDF sample index proves that no wireless
samples were dropped, duplicated, or replaced.

For the initial implementation, a recording with unexplained gaps, duplicates,
counter resets, invalid samples, or unresolved continuity is blocked from
scientific processing with an actionable reason. Do not compact missing time,
fill gaps, or silently retain apparently clean epochs: FIR filtering can spread
contamination across interval boundaries. A later policy for retaining clean
segments needs separate reviewed evidence and must still honor no resampling
and no interpolation. Source inspection may remain available while processing
is blocked. Retain source hashes and integrity decisions in generated provenance
under the active project root; never edit the raw BDF.

### Minimal Studio handoff

Agree a shared semantic contract with the companion Studio plan before coding.
The serialization version, exact file path, and field names are not implemented
or fixed by this document. Reuse existing runtime exports/event logs where they
contain the needed evidence; a small companion record is appropriate only where
compact output otherwise loses it. The contract carries:

- Studio/export version, explicit participant/session/run identifiers, and a
  reviewed association between the experiment session and the EEG recording;
- condition-onset and oddball code mapping, plus ordered emitted events with
  code, label, run, frame, run-relative timestamp, clock origin, and send status;
- acquisition profile, transport endpoint, operator confirmation of Recorder
  raw logging and chosen raw file, and observed or explicitly unknown Recorder
  version and hardware evidence.

Studio must not invent EEG sample indices or claim UDP receipt. Toolbox binds
the external evidence to its canonical participant, recording, session,
condition, and protocol IDs, and reconciles it with recorded STATUS events.
Raw BDF remains the EEG/recorded-marker source. Existing reviewed project
protocols must support explicitly imported external recordings without forcing
all BDFs into a new custom container. Missing, contradictory, or ambiguous
associations require review; filenames are not sufficient authority.

### Timing interpretation and optional calibration

Recorder's marker placement and any internal delay compensation remain unknown
until verified for the installed version/configuration. Distinguish monitor
flip/frame timing, Studio UDP send timing, Recorder placement, and headset
sample timing. Do not guess a fixed Bluetooth delay, subtract published averages,
or apply a second correction to compensation already performed by Recorder.

Default timing state is uncalibrated/uncorrected, with that limitation visible.
This is distinct from a measured zero correction. If existing equipment permits
measurement, support a separately reviewed signed calibration record in analysis
metadata. Define sign convention, source/target clocks, integer-sample rounding,
scope, version/configuration, uncertainty, and evidence. Apply any accepted
offset only to derived event/window coordinates, preserving original samples,
source events, raw bytes, durations, and a reproducible uncorrected view. Require
boundary/collision checks and fingerprint invalidation. No fractional shifting,
interpolated EEG, or time-warp correction is permitted.

The native sample interval is 4 ms. Software timestamp agreement cannot establish
physical onset accuracy within that interval. Implementation and synthetic
transport/import checks can proceed without buying equipment; research timing
qualification may remain blocked if available equipment cannot measure the
needed relationship. Record that limit instead of claiming BioSemi-equivalent
trigger timing or making a new purchase a hidden prerequisite.

## Preprocessing and Analysis Policy

The unresolved reference decision must be made explicit before scientific
qualification: document the headset's acquisition reference and decide whether
the Unicorn analysis retains it or applies an explicitly named eight-channel
average reference. Do not silently use the existing EXG-pair or final-reference
defaults. Persist the decision and invalidate derived outputs when it changes.
Eight-channel and 64-channel average references are not equivalent measurements.

Keep supported FIR/notch settings in their existing sequence at 250 Hz; do not
add an early rate conversion to fit current settings. Characterize the existing
8,449-tap filter and its boundary/duration behavior at 250 Hz, including short
recordings and valid cutoff/Nyquist limits. Any proposed filter-method change
requires a separate documented decision and version, not an incidental import
fix. Reject incompatible Unicorn settings instead of silently substituting them.

Unicorn interpolation is disabled end to end. Reject imported repair requests,
automatic repair decisions, condition-specific repair requests, and cache entries
claiming an interpolated Unicorn result. QC may report signal evidence and let
the user retain/exclude the appropriate recording or condition with reasons.
It may not convert a failed channel into a synthesized channel or silently shrink
an ROI. The current 16-channel normalized-kurtosis method remains unavailable;
manual review is an explicit alternative workflow, not a reduced-threshold
implementation of that method. Gate other BioSemi-calibrated detectors unless
their applicability has been documented.

Reuse exact-cycle extraction, repetition averaging, Fourier amplitude scaling,
BCA subtraction, SNR ratios, local noise/z rules, and harmonic exclusions. At
6 Hz presentation and 1.2 Hz oddballs, 144 analyzed cycles represent 120 seconds
and 30,000 samples at 250 Hz; the exact three-cycle grid is 625 samples. These
are acceptance examples, not a new hardcoded protocol. Nonintegral requested
cycle/sample combinations fail; rounding duration or resampling is forbidden.
The existing +/-10-bin noise window excludes target and adjacent bins, trims
one finite minimum and maximum, and uses population SD. Preserve its applicability
and harmonic-eligibility checks at the actual Nyquist/filter limits.

Define Unicorn ROIs explicitly from available electrodes. A named sensor such
as Oz can be offered as a transparent single-sensor selection; any multi-sensor
ROI needs an explicit saved definition. Existing LOT/ROT membership must not be
reused by silent intersection, relabelled, or populated with missing channels.
Freeze ROI and selection masks in provenance. Isolate device presets so editing
one does not mutate BioSemi definitions or another project's frozen analysis.

Preserve participant x session/recording x condition x ROI structure. Block
mixed-device pooling by default, including indirect aggregation through processed
results, harmonic selection, and plotting. A future harmonization strategy needs
a reviewed common-sensor/reference/protocol policy; having similarly named
electrodes is insufficient.

| Capability | Initial Unicorn disposition |
| --- | --- |
| Import, source inspection, marker review | Enable only after validated source/profile interpretation; processing remains subject to integrity gates. |
| Native-rate preprocessing and sensor-level FFT/BCA/SNR | Enable after reference/QC decisions and numerical qualification. |
| SNR plots, explicit available-sensor ROIs, standard exports/statistics | Qualify through canonical profile-aware provenance and dataset identities; no mixed-device pooling. |
| Automatic normalized-kurtosis decisions and interpolation | Unavailable and disabled respectively; no threshold reduction or hidden repair. |
| Free Harmonic Clustering | Disabled: its fixed 197-edge BioSemi64 adjacency and current validation do not establish an eight-sensor method. |
| Scalp Maps and source estimates/LORETA workflows | Disabled for Unicorn until separately supported and validated; do not pass an eight-sensor subset as BioSemi64 or restore retired source-localization code. |

## Phased Execution and Acceptance Gates

### Phase 0 - Freeze fixtures and remaining decisions

- [ ] Confirm the installed Recorder version and raw BDF+ availability using
  existing software; record unknowns rather than assuming current online behavior.
- [ ] Obtain a short anonymized raw fixture and known marker/amplitude cases;
  record raw/processed distinction, channel mapping, units, sample rate, references,
  telemetry, counter behavior, and header identification fields.
- [ ] Agree the shared Studio handoff semantics/version with the companion plan;
  explicitly record reference policy and continuity requirements.
- [ ] Freeze BioSemi regression inputs and expected stage/output identities before
  touching shared code. Preserve current user changes and active QC decisions.

Gate: a fixture-backed input contract and named unresolved decisions exist.
If raw BDF+ or required integrity evidence is unavailable in the installed
Recorder, report the blocker. Do not install/purchase an SDK or silently switch
to CSV/XDF. Those alternatives require a separately scoped decision.

### Phase 1 - Profile, loading, and integrity boundary

- [ ] Add the smallest explicit profile representation in existing project/I/O
  owners; retain exact BioSemi defaults and validation.
- [ ] Implement matching lazy/full Unicorn loader behavior with strict labels,
  geometry, native rate, units, telemetry separation, and marker decoding.
- [ ] Block invalid/unknown continuity before signal processing; preserve source
  hashes, evidence, and actionable reasons without writing raw files.
- [ ] Register and serialize participant/session/recording associations through
  the existing project APIs, including reviewed external recordings.

Gate: valid fixtures load identically through preflight/full paths; malformed
headers, units, channels, rate, STATUS, or integrity evidence fail explicitly.
No missing BioSemi signals are fabricated and no sample count changes occur.

### Phase 2 - Native-rate preprocessing and manual QC

- [ ] Implement the agreed explicit reference policy, keeping physical REF/GND
  distinct from recorded channels and preserving original evidence.
- [ ] Enforce native 250 Hz before/after every preprocessing/cache path. Reject
  conflicting persisted settings; prove no resampling function is called.
- [ ] Disable every interpolation path and enforce a truthful manual-QC release
  route with normalized kurtosis marked unavailable.
- [ ] Characterize FIR/notch behavior and analytical span boundaries at 250 Hz;
  preserve locked BioSemi order and parameters.

Gate: sample grid stays unchanged, no interpolation occurs, review decisions are
scoped/audited, and no unsupported QC method appears to pass automatically.

### Phase 3 - Provenance, metrics, and supported consumers

- [ ] Propagate acquisition/montage/reference/rate/integrity/marker-calibration
  identity through preflight caches, prepared checkpoints, preprocessing cache,
  ledger, FullFFT provenance, ROI snapshots, and downstream freshness checks.
- [ ] Reuse existing metric and harmonic owners; prove 250 Hz exact-cycle behavior
  and amplitude/noise calculations against independent synthetic expectations.
- [ ] Add explicit Unicorn selections and supported consumer gates. Reject stale
  or mixed profiles and missing ROI members without silently changing cohorts.
- [ ] Preserve native result, workbook/companion, output naming, project-relative
  paths, and participant/session/condition/ROI structure.

Gate: supported sensor/ROI workflows consume one coherent profile; cache reuse
cannot cross profiles or altered scientific settings. BioSemi outputs remain
numerically and structurally unchanged.

### Phase 4 - Project workflow and documentation

- [ ] Add profile selection and concise, accurate settings/status presentation
  using current PySide6 components and worker boundaries.
- [ ] Keep native rate and interpolation-disabled state visible; explain
  unavailable QC/tools and give corrective input actions without fallback modes.
- [ ] Reconcile Studio handoff with recorded events and show known/unknown timing
  status; preserve existing project import and external-recording workflows.
- [ ] Register GUI coverage and a visible/manual smoke path at the supported
  1280x900 workspace. No local offscreen Qt execution.
- [ ] Update loading, preprocessing, project-I/O, post-processing/export,
  statistics/tool, methods-reporting, and user workflow documentation as affected;
  update `ARCHITECTURE.md` and the agent index only where actual ownership/routes
  change. Keep detailed contracts in their canonical documents.

Gate: a user can follow the existing project workflow for supported Unicorn
analysis without technical guesswork, new purchases, or accidental BioSemi preset
changes. Unsupported capabilities remain clearly unavailable.

### Phase 5 - End-to-end qualification and release evidence

- [ ] Run focused backend and project tests, supported-consumer tests, and the
  repository precommit gate; report unrelated failures without repairing them
  opportunistically.
- [ ] With separately authorized use of the existing headset/Recorder, reconcile
  a real Studio session with BDF markers, IDs, continuity, and outputs.
- [ ] Validate any optional calibration from measurements made with available
  equipment, preserving signed/unknown/verified-zero distinctions.
- [ ] Publish separate software-compatibility and timing-evidence conclusions.
  If physical timing remains unmeasured, state it plainly; do not claim the same
  timing accuracy or scientific signal coverage as BioSemi.

Gate: every claimed capability has an evidence receipt; missing research timing
evidence remains a visible qualification limit rather than a fabricated pass.

## Verification Matrix and Commands

Future implementation tests should extend the existing owners rather than
create a parallel test harness:

| Coverage | Existing test anchors and additions |
| --- | --- |
| BDF/header/geometry | `tests/processing/test_shared_load_utils.py`, `test_biosemi64_geometry.py`; add fixture-backed Unicorn label/unit/telemetry validation, full/lazy parity, no fake channels, raw-byte preservation. |
| Preprocessing | `tests/processing/test_filter_downsample_order.py`, `test_preprocess_biosemi64_geometry.py`, `test_preprocess_kurtosis_gate.py`; add native-250 no-call guards for resampling/interpolation, explicit reference, incompatible settings, unavailable normalized kurtosis, manual review outcomes. |
| Events and windows | `tests/processing/test_marker_integrity.py`, `test_analysis_spans.py`, `test_preprocess_trigger_alignment.py`, `test_fft_crop_utils.py`; add single-sample/adjacent-code pulses, missing/duplicate markers, reset/overflow evidence, 30,000-sample example, nonintegral rejection, calibrated offset bounds and collisions. |
| Signal/metric identity | `tests/processing/test_fft_neighbors_sheet.py`, `test_processing_full_fft_provenance.py`, `test_processing_ledger.py`; add known-microvolt spectra/noise, profile/ref/ROI/timing invalidation, altered-source evidence, mixed-device rejection, and unchanged BioSemi golden results. |
| Project/consumer identity | `tests/project_io/test_project_geometry_persistence.py`, `test_frequency_protocol.py`, `test_project_dataset_index.py`, `test_fpvs_config_import.py`; add saved/reopened profiles, participant/session associations, unchanged legacy manifests, preset isolation, supported plots/exports, and unavailable-tool gates. |
| Failure behavior | Gaps, duplicated samples, unknown telemetry semantics, disconnected/restarted recording, incomplete file, wrong units/rate/profile, unsupported repair requests, conflicting handoff IDs, cancellation, and stale caches must fail with scoped reasons rather than produce misleading results. |

Use `.venv1` through the repository verification driver. Commands below are
planned implementation gates, not evidence that tests ran during plan creation:

```console
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope plot-generator --tier focused
python .agents/scripts/verify.py --scope stats --tier focused
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Run additional affected consumer scopes only when implementation reaches those
boundaries. Register new coverage in the normal verification configuration.
Qt execution remains CI-only or explicitly approved in a safe visible local
environment; acquisition and physical-timing checks require separate execution
authorization and available equipment. No tests, EEG acquisition, or hardware
qualification are part of this documentation-only task.

## Completion Checklist

- [ ] Raw BDF+ and native 250 Hz are verified with no resampling or interpolation.
- [ ] Units, eight-channel mapping, reference, continuity, STATUS, and Studio
  associations are explicit, validated, and preserved in provenance.
- [ ] Manual QC truthfully handles unsupported normalized kurtosis; missing data
  cannot be accepted through a hidden repair or pass state.
- [ ] FFT/BCA/SNR and harmonic contracts are preserved; BioSemi golden results,
  legacy manifests, presets, and caches remain unchanged where intended.
- [ ] Participant/session/condition/ROI identity and supported exports are intact;
  mixed-device aggregation and unsupported spatial tools are blocked.
- [ ] Optional timing correction is measured, signed, reversible in analysis,
  and never written into raw BDF; unknown timing is never called calibrated zero.
- [ ] No paid interface, purchase, new equipment, broad acquisition framework,
  CSV/XDF feature, or source-localization restoration was introduced.
- [ ] Documentation and execution-plan status match demonstrated capability,
  with software and research timing validation reported separately.

## Plan-Creation Verification

Only this plan and its entry in `docs/agent/exec-plans/README.md` are intended
changes in the plan-writing task. Runtime architecture and scientific contracts
are unchanged, so their current documentation must not be rewritten to describe
planned support as already available. Record narrow documentation checks in the
handoff; implementation checkboxes remain pending.
