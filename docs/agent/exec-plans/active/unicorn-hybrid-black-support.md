# Unicorn Hybrid Black Support

Status: Active implementation

Created: 2026-09-25. Implementation authorized and started: 2026-09-29 on
`codex/unicorn-headset-support`, based on `codex/v3-release` at `4aac39c8`.
The 2026-09-28 revision requires explicit BDF+ support and a modular loader
that can accept future electrode montages. Checkboxes below track demonstrated
capabilities; source inspection alone does not qualify scientific processing.

Companion plan: FPVS-Studio-2.0 repository,
`docs/exec-plans/active/unicorn-hybrid-black-support.md` (current Studio
working-tree location; recheck its committed location when implementation starts).

## Objective and Fixed Decisions

Support the user's existing Unicorn Hybrid Black through this workflow:
FPVS Studio sends local UDP event codes to the vendor Recorder; the Recorder
writes raw BDF or BDF+; Toolbox imports that recording through an explicit
Unicorn acquisition profile and a modular loading boundary, then reuses its
reviewed condition, FFT, BCA, SNR, and export workflow. Support classic BDF and
continuous BDF+ (BDF+C), including recorded annotations. Detect and inspect
BDF+D discontinuities, but block scientific processing under the continuity
policy below. BioSemi acquisition and existing results must remain unchanged.
Future electrode montages must be addable through registered definitions and
contract tests without rewriting loader orchestration or the processing pipeline.

The user has fixed these boundaries:

- No new purchases, paid SDK/API, extra amplifier, trigger box, or equipment.
  Use the existing headset, computer, and available vendor Recorder. Do not make
  implementation depend on access to a paid programming interface.
- Raw classic BDF and continuous BDF+ are required inputs. Processed Recorder
  output is not a substitute for raw EEG. Both variants use `.bdf`; identify
  the actual format from the header, never the extension or GUI logger caption.
  A validated classic BDF must not be rejected merely for lacking annotations.
- Use a small, versioned in-repository registry separating format adapters,
  acquisition profiles, montage definitions, and event decoders. CSV/XDF/LSL,
  a headset SDK, live acquisition, dynamic plugins, and external plugin discovery
  remain separate scopes; extensible file loading does not require them.
- The eight electrode positions are Fz, C3, Cz, C4, Pz, PO7, Oz, and PO8.
  Verify their recorded-label mapping explicitly; channel number alone is not
  evidence of electrode position.
- Keep Unicorn data at native 250 Hz throughout analysis. No downsampling,
  upsampling, resampling, or time-grid regularization is permitted. Fail on an
  incompatible sampling grid instead of changing it.
- Disable EEG interpolation for Unicorn, including automatic, manual,
  recording-wide, and condition-specific repair routes. Missing channels or
  samples must never be zero-filled or reconstructed to resemble BioSemi64.
- User decision on 2026-09-29: use the explicitly named eight-scalp-channel
  average reference (`average_scalp`), not a retained-reference alternative.
  Physical acquisition reference and amplitude qualification remain evidence
  questions; neither physical mastoid electrode is a recorded scalp channel.
- Preserve the core FFT/BCA/SNR arithmetic, neighboring-noise definitions,
  protocol-owned harmonic rules, repeated-measures identities, and export
  contracts. Device differences must remain visible in provenance.
- Local UDP connects Studio to Recorder on the same computer; the headset's
  Bluetooth EEG link is a separate path. Software send time is not proof of
  recorded-sample alignment or physical stimulus onset.

## Evidence and Existing Owners

The original investigation inspected branch `codex/v3-release`, commit
`6de199039649173e085eeb059d699981ccecd617`, with pre-existing QC/settings work.
This plan revision starts from `5542f985` on the same branch. Line references
are historical navigation aids and must be rechecked during implementation.
Preserve unrelated work and current scientific decisions.

The vendor's [Recorder manual](https://github.com/unicorn-bi/Unicorn-Recorder-Hybrid-Black/blob/main/README.md)
documents a raw BDF+ logger, EEG in microvolts, STATUS trigger values, and
optional counter, validity, battery, and timing signals. It also documents UDP
trigger reception. This supports the proposed route, but does not establish
the installed Recorder version's exact header, timing behavior, or data-loss
semantics. Those require fixtures from the user's existing installation.

### Receiver evidence obtained on 2026-09-28

Unicorn Recorder 1.24.02 (executable 1.24.2.2760) produced a raw test-signal
recording named `UnicornRawDataRecorder_28_09_2026_12_41_18.bdf`. Its header
identifies classic BDF (`24BIT`), with no BDF Annotations channel. It has
22,621 samples at 250 Hz, `EEG 1` through `EEG 8`, `CNT`, `VALID`,
`DT`, and `Status`. The companion CSV calls the marker column `TRIG`.
Raw Status and CSV TRIG match at every sample; all 426 transmitted codes match
in order, including all values 1-255 and adjacent repeated codes. The retained
receiver/sender receipts are in the user's Studio diagnostics bundle
`Unicorn/2026-09-28-2bce2ff1`; reference that evidence rather than committing
machine-specific absolute paths or assuming it is already a portable fixture.

An isolated check with Toolbox's pinned MNE 1.9.0 found that its current
`find_events(..., shortest_event=1)` settings return 419 markers from this
file. `consecutive=True` returns 422; four adjacent equal-code pairs still
merge. The existing BioSemi geometry validator separately rejects missing
`EXG1`. These are distinct loader/event-contract failures, not evidence that
the raw recording lost the triggers. Freeze them as implementation regressions.
This test does not qualify BDF+ output, physical display timing, electrode-label
mapping, reference policy, amplitude accuracy, or telemetry semantics. Counter
increments and VALID=1 in this fixture do not establish all vendor loss rules.

BDF+ support must have separate format fixtures, initially generated if needed,
and an evidence label distinguishing format conformance from vendor acquisition
qualification. The [BDF+ specification](https://www.teuniz.net/edfbrowser/bdfplus%20format%20description.html)
and its [annotation/timekeeping contract](https://www.edfplus.info/specs/edfplus.html)
are the format references; a vendor logger caption is not format evidence.

| Current owner | Verified behavior and planned implication |
| --- | --- |
| `src/Main_App/io/load_utils.py`; `src/Main_App/Shared/load_utils.py:609` | Public loading API delegates to the shared owner. Full and lazy preflight paths currently validate the complete BioSemi header before returning Raw. Resolve registered format/acquisition/montage/event contracts before device validation; retain one canonical loading surface and strict BioSemi rules. |
| `src/Main_App/io/eeg_geometry.py`; `src/Main_App/Shared/eeg_geometry.py:361` | BioSemi validates exactly 64 scalp signals, two recorded EXG references, stimulus, and supported auxiliaries. Keep this validator strict and separate from Unicorn validation. |
| `src/Main_App/projects/preprocessing_settings.py:142` | Current montage, references, and default downsampling settings are BioSemi-oriented. Persist explicit Unicorn acquisition, reference, native-rate, and repair-disabled policy without changing legacy defaults. |
| `src/Main_App/processing/preprocess.py:1129` | Initial EXG-pair reference, channel removal, and final average reference are existing BioSemi behavior. Do not route Unicorn through a missing-reference warning or synthesize EXG signals. |
| `src/Main_App/processing/preprocess.py:432`, `:1373`, `:1540` | FIR duration scaling, zero-double Hamming FIR, and filter-before-downsample order are locked. Current code only resamples when source rate exceeds target. Unicorn must explicitly disable all sample-rate changes rather than rely on 250 being below 256. |
| `src/Main_App/Performance/process_runner.py:213`, `:1896`, `:2256` | Source and processed events are compared with reviewed analysis spans. Replace duplicated discovery with one profile-selected canonical event contract, supporting tested Unicorn Status and explicit BDF+ annotation mappings without guessed numbering. |
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

Use versioned, validated definitions in existing project/I/O owners, resolved
once per source into an immutable recording context. An acquisition profile
references compatible montage and event-decoder IDs; the BDF adapter can serve
multiple acquisitions and montages. A montage alone must not choose reference,
sample-rate, telemetry, or trigger semantics. Unknown IDs/versions, ambiguous
mappings, and incompatible combinations fail explicitly; channel count, file
extension, and missing EXG channels are not authority to infer Unicorn.

A missing profile in an existing project must retain the exact current BioSemi
interpretation, serialization, and scientific fingerprint behavior. Introducing
the registry must not invalidate unchanged legacy results solely because their
internally resolved profile now has a name. Explicitly version actual changes.

### Modular loading and processing handoff

Keep `Main_App.io.load_utils` as the public loading surface and
`Main_App.io.eeg_geometry` as the geometry surface. Introduce small GUI-neutral
contracts behind these APIs; migrate the shared implementation only as needed,
without creating a second loader or device-specific processing pipelines.

| Component | Responsibility and extension boundary |
| --- | --- |
| Format adapter | Read headers, physical units/scaling, samples, annotations, source time origin, and BDF/BDF+C/BDF+D identity. Own lazy/full resource lifecycle. No electrode-position or device-reference guesses. |
| Acquisition profile | Declare recorded EEG/reference/stim/telemetry roles, compatible montages and decoders, native-rate/reference/integrity policies, and validated capabilities. Do not assume every acquisition has EXG or a recorded stim channel. |
| Montage definition | Freeze anatomical sensor identities/order, coordinates with source/version/frame, and explicit label/wiring mappings. Validate complete headers before subset reads; never reorder signal values into different electrode identities. |
| Event decoder | Decode the declared Status or annotation semantics into canonical ordered events; preserve source values/times and exact native-sample interpretation. Reuse reviewed BioSemi edge semantics and isolate Unicorn sample-wise semantics. |
| Common orchestration | Resolve and validate registered components, retain resource/subset/error behavior, and pass one validated recording context to existing preprocessing, QC, and export owners. Numerical stages consume capabilities and policies, not scattered device-name branches. |

Use explicit built-in registration, immutable definitions, unique stable IDs,
versions, and compatibility validation. Registration must not depend on GUI
imports or import order. Ordinary montage additions change a definition/mapping,
compatibility registration, and fixtures; a genuinely new format or event
encoding may need its own adapter, but must not rewrite common orchestration.

Full loading, lazy preflight, source prefetch, and their cache/checkpoint paths
must resolve the same context and produce equivalent geometry, units, event
records, integrity decisions, and fingerprints. Preserve existing public return,
error, cancellation, memmap, and cleanup behavior through compatibility facades.
The internal handoff includes Raw in volts, source rate/sample count/time origin,
canonical events, annotations, integrity evidence, selected component IDs/versions,
and capability policy. Keep project paths/runtime handles out of persisted
scientific definitions; workers receive serializable identities/settings.

Reference stages, channel selection, sample-rate policy, interpolation, QC,
ROIs, and downstream tools must consult that validated context. A new montage
cannot implicitly enable an unqualified spatial method or alter locked BioSemi
stage order. Reject unsupported capability requests before mutating EEG. Document
an extension checklist and prove it with a third synthetic montage registration
that reaches common preprocessing without editing orchestration or metric code.

### Channel and unit interpretation

Freeze the physical-to-recorded mapping from a fixture. Preserve source channel
order; normalize labels only through that explicit mapping. Physical REF/GND
electrodes are not additional EEG signals unless the file actually records
them. Keep STATUS as stimulus and supported telemetry as auxiliary data, never
as scalp EEG, average-reference members, ROIs, or harmonic-selection electrodes.

The common processing boundary remains MNE Raw with EEG in volts, native
250 Hz for Unicorn, validated channel geometry, canonical native-grid event
records, and separate source-integrity evidence. Validate BDF physical/digital
ranges and reader scaling against a known input before choosing any conversion. Do not
multiply EEG already converted to volts by another microvolt scale factor.

### BDF+ annotations and canonical events

Continuous BDF+ support must work with Status-only markers, annotation-only
markers, and both sources together. Preserve all annotation descriptions,
onsets, durations, and time origins; separate protocol markers from operator
notes, artifact intervals, and format timekeeping. Retain notes for inspection
and provenance without automatically treating them as triggers or approval to
exclude EEG. Annotation-only input must not be rejected for lacking Status.
The canonical event table, not a fabricated stim waveform, is authoritative.

Decode numeric annotations using an explicit validated numeric rule and named
annotations using a persisted protocol mapping. Preserve codes 1-255 and their
meaning; never use MNE's alphabetical/automatic annotation IDs as protocol codes.
Unknown marker labels require a decision; preserve unrelated notes separately.
Resolve event-source authority explicitly. When both sources claim the same
markers, reconcile code/order/sample positions and report conflicts; never
concatenate them and double-count events or silently switch to a fallback.

Each event retains stable source identity/order, code, source channel or
annotation text, original onset/duration, native integer sample index, and the
mapping/decoder version. Define time origin (including first-sample/segment
offsets), integer rounding/tie rule, residual quantization, boundary checks, and
collision policy. Off-grid timestamps or multiple events resolving to one sample
must remain visible; block analysis that cannot represent them without loss.
Do not resample EEG, guess clock offsets, collapse equal adjacent events, or
claim annotation decimal precision proves acquisition timing accuracy.

For the observed Unicorn Status encoding, every validated nonzero source sample
represents one marker, including equal or decreasing adjacent codes. Confirm
that contract for the Recorder version/configuration before qualification; do
not impose it on BioSemi or other level/edge-based encodings. Preflight, marker
review, analyzed-span planning, preprocessing alignment, condition extraction,
and export must all consume the same decoded events. Update current stim-only
assumptions, including analysis-span handling, instead of leaving a second
`find_events` path downstream that can discard events again.

### Continuity and raw evidence

Inspect the BDF variant before a reader can flatten or discard discontinuity
information. Preserve BDF+ record timestamps and declared gaps in source evidence.
BDF+D is inspectable but blocked from scientific processing in this first release;
unknown/malformed timing fails explicitly. Continuous BDF+C must still pass the
same telemetry/integrity rules as classic BDF. A continuous header alone does not
prove uninterrupted wireless acquisition.

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
condition, and protocol IDs, and reconciles it with canonical recorded events
from the selected Status/annotation decoder. Raw BDF/BDF+ remains the EEG and
recorded-marker source; Studio send logs cannot replace missing receiver events.
Existing reviewed project protocols must support explicitly imported external recordings without forcing
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

The user selected the explicitly named eight-channel average reference on
2026-09-29. Document the headset's acquisition reference before scientific
qualification; the analysis decision does not establish that hardware fact.
Do not silently use the existing EXG-pair or final-reference defaults. Persist
the decision and invalidate derived outputs when it changes.
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

- [x] Package/reproduce the retained classic-BDF receiver evidence as an
  anonymized, checksum-bound regression fixture with expected codes/sample indices.
  Record Recorder version/configuration and outstanding acquisition unknowns.
  The portable fixture is a sanitized receipt with exact events and raw-source
  checksums, not a redistributed recording or a scientific-qualification claim.
- [x] Add independent BDF+C fixtures with Status-only, annotation-only, and dual
  event sources, plus BDF+D/gap/malformed-time cases. Generated format fixtures
  must not be presented as proof that this Recorder writes BDF+.
- [ ] Obtain known amplitude/reference and mapping evidence; record raw/processed
  distinction, channel roles/positions, units, native rate, telemetry semantics,
  counter behavior, and header identification fields.
- [ ] Agree the shared Studio handoff semantics/version with the companion plan;
  explicitly record reference policy and continuity requirements.
- [ ] Freeze BioSemi regression inputs and expected stage/output identities before
  touching shared code. Preserve current user changes and active QC decisions.

Gate: a fixture-backed input contract and named unresolved decisions exist.
Classic BDF availability is sufficient to develop Unicorn acquisition support;
BDF+ format support is a separate required software gate, not an excuse to
convert or reject valid classic BDF. Missing integrity/reference evidence blocks
scientific qualification, not isolated format/contract tests. Do not purchase an
SDK or silently switch to CSV/XDF. Those alternatives require separate scope.

### Phase 1 - Profile, loading, and integrity boundary

- [ ] Define and register format, acquisition, montage, event, and capability
  contracts behind existing public owners; retain exact BioSemi defaults and
  validation, including legacy settings/fingerprint behavior.
- [ ] Implement classic BDF/BDF+C reading and explicit BDF+D inspection/blocking,
  with annotation preservation and deterministic event-source reconciliation.
- [ ] Implement equivalent lazy/full/prefetch behavior with strict labels,
  geometry, native rate, units, telemetry separation, and canonical events.
- [ ] Prove all 426 observed Unicorn markers survive every event-consuming path,
  including adjacent equal/decreasing codes; keep BioSemi edge behavior unchanged.
- [ ] Add a third test-only montage/profile using existing format/event adapters
  through registration alone. Prove common loading and preprocessing need no
  device/montage-specific code edit; reject incompatible registrations.
- [ ] Block invalid/unknown continuity before signal processing; preserve source
  hashes, evidence, and actionable reasons without writing raw files.
- [ ] Register and serialize participant/session/recording associations through
  the existing project APIs, including reviewed external recordings.

Gate: valid classic BDF/BDF+C fixtures have matching lazy/full/prefetch contracts;
annotation-only events reach common analyzed-span planning without fake channels.
Malformed headers, units, channels, rate, events, or integrity fail explicitly.
BDF+D cannot silently become continuous EEG. The third-registration test passes
without changing common orchestration, sample counts, or BioSemi interpretation.

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

- [ ] Propagate format/acquisition/montage/decoder IDs and versions, source
  annotation/event mapping and authority, coordinate fingerprints, capability,
  reference/rate/integrity/calibration identity through preflight caches, prepared
  checkpoints, preprocessing cache, ledger, FullFFT provenance, ROI snapshots,
  and downstream freshness checks. Changing relevant definitions invalidates
  affected outputs; unrelated profile additions do not invalidate BioSemi.
- [ ] Reuse existing metric and harmonic owners; prove 250 Hz exact-cycle behavior
  and amplitude/noise calculations against independent synthetic expectations.
- [ ] Run equivalent Status-only, annotation-only, and dual-source BDF+C fixtures
  through preprocessing, condition extraction, FFT/BCA/SNR, and canonical exports.
  Require matching event sample identities, selected spans, and numerical outputs;
  reader/preflight-only success is insufficient for BDF+ support.
- [ ] Add explicit Unicorn selections and supported consumer gates. Reject stale
  or mixed profiles and missing ROI members without silently changing cohorts.
- [ ] Preserve native result, workbook/companion, output naming, project-relative
  paths, and participant/session/condition/ROI structure.

Gate: supported sensor/ROI workflows consume one coherent profile; cache reuse
cannot cross profiles or altered scientific settings. BioSemi outputs remain
numerically and structurally unchanged.

### Phase 4 - Project workflow and documentation

- [ ] Add compatible profile/montage selection and concise settings/status
  presentation from registered definitions using current PySide6 components and
  worker boundaries; reject unsupported combinations before loading.
- [ ] Keep native rate and interpolation-disabled state visible; explain
  unavailable QC/tools and give corrective input actions without fallback modes.
- [ ] Reconcile Studio handoff with recorded events and show known/unknown timing
  status; preserve existing project import and external-recording workflows.
- [ ] Register GUI coverage and a visible/manual smoke path at the supported
  1280x900 workspace. No local offscreen Qt execution.
- [ ] Update loading, preprocessing, project-I/O, post-processing/export,
  statistics/tool, methods-reporting, and user workflow documentation as affected;
  update `ARCHITECTURE.md` and the agent index only where actual ownership/routes
  change. Keep detailed contracts in their canonical documents. Include the
  montage-extension checklist, registration/compatibility rules, and common
  contract-test requirements; distinguish BDF+C support from BDF+D inspection.

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
| BDF/header/geometry | `tests/processing/test_shared_load_utils.py`, `test_biosemi64_geometry.py`; add classic BDF/BDF+C fixtures, BDF+D detection without flattened gaps, annotation preservation, strict Unicorn label/unit/telemetry validation, lazy/full/prefetch parity, no fake channels, raw-byte preservation. |
| Registry and extension contract | Add focused contract tests under existing processing/project test owners: a third synthetic montage/profile reuses format/event adapters and reaches common preprocessing without orchestration edits; duplicate/unknown IDs or versions, incompatible pairs, ambiguous mappings, incomplete headers, altered coordinates, and unsupported capabilities fail. Definition additions must not mutate existing profiles or project snapshots. |
| Preprocessing | `tests/processing/test_filter_downsample_order.py`, `test_preprocess_biosemi64_geometry.py`, `test_preprocess_kurtosis_gate.py`; add native-250 no-call guards for resampling/interpolation, explicit reference, incompatible settings, unavailable normalized kurtosis, manual review outcomes. |
| Events and windows | `tests/processing/test_marker_integrity.py`, `test_analysis_spans.py`, `test_preprocess_trigger_alignment.py`, `test_fft_crop_utils.py`; add the 426-marker fixture (419/422 are failing regressions), adjacent equal/decreasing codes, all codes 1-255, Status-only/annotation-only/dual-source parity, deterministic mappings and conflict rejection, annotation origin/duration/rounding/collisions, repeated text, notes excluded from markers, end-to-end source-sample identity, missing/duplicate markers, reset/overflow evidence, 30,000-sample example, nonintegral rejection, calibrated offset bounds and collisions. |
| Signal/metric identity | `tests/processing/test_fft_neighbors_sheet.py`, `test_processing_full_fft_provenance.py`, `test_processing_ledger.py`; add equivalent BDF+C Status/annotation/dual-source end-to-end metric/export results, known-microvolt spectra/noise, profile/ref/ROI/timing invalidation, altered-source evidence, mixed-device rejection, and unchanged BioSemi golden results. |
| Project/consumer identity | `tests/project_io/test_project_geometry_persistence.py`, `test_frequency_protocol.py`, `test_project_dataset_index.py`, `test_fpvs_config_import.py`; add saved/reopened profiles, participant/session associations, unchanged legacy manifests, preset isolation, supported plots/exports, and unavailable-tool gates. |
| Failure behavior | Gaps, duplicated samples, unknown telemetry semantics, disconnected/restarted recording, incomplete file, wrong units/rate/profile, unsupported repair requests, conflicting handoff IDs, cancellation, and stale caches must fail with scoped reasons rather than produce misleading results. |

Use the repository verification driver (`.venv1`, otherwise `.venv`). Commands
below are planned implementation gates, not evidence that tests ran during
plan creation:

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
authorization and available equipment. Implementation authorization covers
software changes, source-evidence inspection, and backend verification.

## Completion Checklist

- [ ] Raw classic BDF and BDF+C, including annotation-only events, are verified;
  BDF+D timing is preserved for inspection and scientific processing is blocked.
- [ ] Registered format/acquisition/montage/event contracts share one pipeline;
  a third montage passes extension tests without common orchestration edits.
- [ ] Native 250 Hz is preserved with no resampling or interpolation. Units,
  eight-channel mapping, reference, continuity, all 426 fixture markers, explicit
  BDF+ event mappings, and Studio associations are validated in provenance.
- [ ] Manual QC truthfully handles unsupported normalized kurtosis; missing data
  cannot be accepted through a hidden repair or pass state.
- [ ] FFT/BCA/SNR and harmonic contracts are preserved; BioSemi golden results,
  legacy manifests, presets, and caches remain unchanged where intended.
- [ ] Participant/session/condition/ROI identity and supported exports are intact;
  mixed-device aggregation and unsupported spatial tools are blocked.
- [ ] Optional timing correction is measured, signed, reversible in analysis,
  and never written into raw BDF; unknown timing is never called calibrated zero.
- [ ] No paid interface, purchase, new equipment, live acquisition framework,
  dynamic plugin system, CSV/XDF feature, or source-localization restoration was
  introduced; the required built-in loader registry stays within scope.
- [ ] Documentation and execution-plan status match demonstrated capability,
  with software and research timing validation reported separately.

## Implementation Log

- 2026-09-29: Created the implementation branch from the current release branch
  and activated this plan. Initial protected-path and project-path audits pass.
  Reviewing retained Recorder evidence, Studio handoff, and current loading,
  event, preprocessing, and provenance contracts before shared runtime edits.
- 2026-09-29: Added read-only inspection behind
  `Main_App.io.load_utils.inspect_eeg_recording`, immutable versioned acquisition
  definitions, strict BDF/BDF+C/BDF+D byte inspection, explicit native-grid
  marker decoding/reconciliation, and a candidate Studio handoff adapter.
  No existing BioSemi loading, preprocessing, settings, fingerprints, or GUI
  choices were changed. This is the Phase 0 / early Phase 1 foundation, not
  completed headset support; the remaining phase gates stay unchecked.
- Independently read the original retained BDF through the new inspector:
  SHA256 `9fa2e01480fae7a1500f92cc8739fa2a036f9b87b1f00fef429712a73c6a6a0c`,
  22,621 samples, 426 events with exact receipt code/sample equality. Scientific
  processing stays blocked. EEG dimension bytes are literally `3F 56` (`?V`),
  not a text-decoding artifact, and CNT has nonidentity physical scaling.
- Read-only amplitude probe on that same BDF/CSV pair: header-calibrated EEG
  versus CSV differs by at most 0.05699 physical units (one digital LSB is
  0.089407); CNT differs by at most 0.47695 (one LSB is 0.953674). MNE 1.9
  returns the EEG header-physical values unchanged for `?V` (EEG 1 maximum
  absolute value 75,379.1526), not volts. Thus the vendor's documented microvolt
  interpretation cannot pass unchanged into the volts-based pipeline. This is
  evidence for a future explicitly qualified unit rule, not permission to silently
  add one or claim hardware amplitude accuracy. The generated-format regression
  freezes this reader behavior for a nonzero `?V` signal.
- Manufacturer layout evidence: the
  [numbered cap diagram](https://github.com/unicorn-bi/Unicorn-Suite-Hybrid-Black-User-Manual/blob/main/UnicornHybridBlack.md#connect--disconnect-unicorn-hybrid-eeg-electrodes)
  ([diagram](https://raw.githubusercontent.com/unicorn-bi/Unicorn-Suite-Hybrid-Black-User-Manual/main/img/img3.png))
  plus the Recorder's channel numbering supports the factory mapping EEG 1-8
  to Fz, C3, Cz, C4, Pz, PO7, Oz, PO8. Registered factory mapping is explicit
  opt-in, not authority to infer custom wiring. The user chose eight-channel
  average reference. No channel-number-only or missing-EXG inference is used.
- Studio's observed envelope uses top-level string schema `1.0`, nested
  RecordingSnapshot integer schema `1`, and status
  `candidate_receiver_validation_pending`. The adapter preserves that status,
  repeated/error attempts, and run-relative callback times. A caller-reviewed
  recording binding is necessary for code-order comparison; no sample alignment
  or calibration is inferred. The companion active plan's 148-marker follow-up
  reports about 118.31 ms interval growth over 146 oddball intervals; it does
  not establish a causal explanation or justify a timing correction.

### Remaining qualification and integration gates

- Qualify the Recorder's `?V` interpretation against known amplitude/reader
  scaling, acquisition reference, raw-logging evidence, and CNT/VALID/DT loss
  semantics. A vendor layout diagram does not establish any of these.
- Integrate the context through lazy/full/prefetch loading and every production
  event consumer. The new 426-event decoder regression is not a claim that the
  unchanged production event consumers preserve those markers already.
- Complete native-250/no-interpolation preprocessing, explicit manual QC,
  cache/ledger/FullFFT identities, ROI/spatial/mixed-device gates, and project/GUI
  integration before enabling Unicorn in the application. The third synthetic
  profile test currently reaches inspection only, not common preprocessing.
- Hardware/timing validation remains separately authorized. There is no new
  purchase, SDK dependency, resampling, guessed timing offset, or raw-file edit.

### Verification of the inspection foundation

- New focused contracts: 217 passed, including a generated one-sample-per-record
  classic-BDF replay of all 426 retained receipt events through the public
  inspector. This replay is explicitly not the vendor recording; original-byte
  verification was the separate read-only check recorded above.
- `verify.py --scope project-io --tier focused`: 488 passed before the final
  receipt-replay test addition; the final new-contract rerun above includes it.
- `verify.py --scope processing --tier focused`: 2,122 passed, 5 skipped.
- `verify.py --scope repo --tier precommit`: all audits, Ruff and compilation
  passed; 5,418 tests passed, 11 skipped. The final receipt-replay test/helper
  adjustment subsequently passed the 217-test focused rerun.
- Initial sandboxed project-I/O execution had two Windows named-pipe access
  failures; the approved outside-sandbox rerun passed. No production workaround
  or test behavior change was made for these environment restrictions.
- No Qt, live Recorder, headset acquisition, physical timing experiment, or
  project-processing run was launched. Existing short-fixture filter and
  statistics warnings remain; these are not new scientific qualification.
