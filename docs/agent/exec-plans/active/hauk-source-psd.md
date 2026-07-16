# Hauk-Informed Source PSD Workflow

Status: implemented
Owner: FPVS Toolbox
Feature branch: `codex/hauk-source-psd`

## Goal

Replace the normal amplitude-workbook projection routes for new L2-MNE and
eLORETA source-map builds with time-domain-first source-frequency workflows.
The two methods share FPVS Toolbox preprocessing, frequency QC, significant-harmonic
selection, source-cohort, exact-bin, z-score, prepared-payload, and rendering
contracts while retaining independent inverse calculations and source arrays.

This is a Toolbox adaptation of the source-analysis sequence described by Hauk and colleagues, not a claim of byte-for-byte reproduction of the public reference scripts.

## Locked Product Decisions

- The supported input is EEG only. MEG input is out of scope.
- The intended anatomy is the MNE `fsaverage` template with the Toolbox BioSemi64 EEG geometry. Individual MRI/coregistration workflows are out of scope.
- The locked sensor preprocessing order and numerical behavior do not change.
- Repetitions are averaged in the signed time domain before source spectral estimation.
- L2-MNE source spectra use MNE minimum-norm estimation with `method="MNE"`,
  `lambda2=1/9`, `loose=0.2`, `depth=None`, and no
  dSPM/sLORETA/eLORETA normalization. The default method identity is
  `l2_mne_hauk_source_psd_cortical_normal_v1`; it calls MNE source PSD with
  `pick_ori="normal"` so the cortical surface-normal component is selected
  before power-to-amplitude conversion. Source Map Options may explicitly use
  historical `l2_mne_hauk_source_psd_v1` to reproduce older maps that pooled
  free orientations through MNE source PSD.
- eLORETA uses a separately prepared MNE volume inverse with
  `method="eLORETA"`, `lambda2=1/9`, a 10 mm fsaverage volume grid,
  `loose=1.0`, and `depth=None`. It is computed from the same signed FIFs,
  not from L2-MNE z-score or power arrays. The current method identity is
  `eloreta_volume_hauk_source_psd_vector_norm_v1`: complex periodic-Hann
  coefficients are computed at only the exact required bins, passed through
  `apply_inverse(..., pick_ori="vector")`, and reduced per source as
  `sqrt(sum(abs(Cxyz)^2))`. Historical
  `eloreta_volume_hauk_source_psd_v1` outputs remain readable but are labeled
  legacy because their pooled free-orientation result is basis-dependent.
- The EEG-only template inverse uses MNE's ad-hoc diagonal EEG covariance because Toolbox projects do not require a separate resting/noise recording. This intentionally differs from the recorded resting covariance used by the reference study and is preserved in output provenance.
- Project-selected significant oddball harmonics remain the source harmonic plan. Base-frequency overlaps remain excluded by the existing selection contract.
- Exact FPVS frequency-bin identity is required; nearest-bin substitution is forbidden.
- The Toolbox neighboring-bin rule is intentional: offsets `-10..-2` and `+2..+10`, followed by removal of one minimum and one maximum finite noise value and population-SD z scoring (`ddof=0`). This yields nine candidate bins per side before trimming and is a named Toolbox adaptation where it differs from interpretations of the Hauk reference method.
- Current amplitude-derived L2-MNE and eLORETA manifests remain readable as legacy/exploratory outputs. They are not silently relabeled as time-domain source PSD.
- A normal rebuild generates `l2_mne_hauk_source_psd_cortical_normal_v1` and
  `eloreta_volume_hauk_source_psd_vector_norm_v1`. The GUI can substitute the
  explicit legacy L2 method for the former when reproducing older maps. Neither
  time-domain method falls back to `FullFFT Amplitude (uV)` or the Stats-ready
  workbook.
- The eLORETA route is a Hauk-informed Toolbox extension of the source-spectrum
  sequence, not a claim that Hauk et al. implemented this exact EEG-only
  fsaverage eLORETA volume workflow.
- The cortical-normal L2 orientation choice matches the Hauk source estimator
  more closely than the historical pooled-orientation route. It remains a
  Toolbox adaptation because anatomy, modality, covariance, preprocessing, and
  neighboring-bin details differ from the reference study.
- Source orientation and vector pooling are calculation-side contracts. The
  renderer and display selectors consume prepared values without recomputing or
  reinterpreting them.
- Source settings and generated-output state do not expand `project.json` in this phase.
- Project source inference uses one explicit complete-case cohort. A completed
  participant with any missing canonical condition or an explicitly incomplete
  source derivative is omitted from every source condition, with durable
  source-only provenance and a visible warning; it is never dropped
  condition-by-condition or added to the general project exclusion workbook.

## Architecture Contract

### Processing derivative

While condition `EpochsArray` objects are still resident, the Main App writes one averaged, signed EEG Raw FIF per participant and condition plus JSON provenance. A participant commit manifest is published last, after all expected condition files succeed.

Canonical project-relative layout:

```text
6 - Source Localization/
  Source-Ready Time Domain v1/
    <condition>/
      <group when applicable>/
        <participant>_<condition_id>_avg_raw.fif
        <participant>_<condition_id>_avg_raw.json
    manifests/
      <group when applicable>/
        <participant>.json
```

The derivative is a durable generated project output, not the resettable `.fpvs_cache/preprocessed` cache. It contains EEG only, volts, exact processed sampling frequency and sample count, the existing montage/reference/projector state, and no FFT, magnitude, rectification, spectral window, or source calculation.

The sidecar records schema/method version, participant/group/condition/event identity, source-file signature, processing fingerprint/version, MNE version, sample/bin contract, ordered channels/types/units, reference and bad-channel provenance, repetition/crop metadata, future-compatible resolved rate/modulation fields, and a content checksum.

### Source producer

All inverse and source-spectrum math stays in `src/Tools/LORETA_Visualizer/source_producers/`. Project orchestration first derives the explicit source-eligible complete-case cohort. A read-only project adapter then strictly validates a complete participant manifest for every retained participant and loads one participant-condition derivative at a time. Each producer uses its own EEG-only fsaverage inverse model, obtains source amplitudes at the same exact required bins, sums aligned target/noise positions across selected harmonics in its own source space, and applies the same Toolbox neighboring-bin z-score rule. L2-MNE cortical values, eLORETA volume values, caches, and cluster arrays remain method-specific.

More specifically, default L2-MNE obtains cortical-normal PSD with
`pick_ori="normal"` and then converts power to amplitude. Current eLORETA does
not pool scalar source PSD: it preserves complex exact-bin periodic-Hann
coefficients through a vector eLORETA inverse and pools the three output
components with `sqrt(sum(abs(Cxyz)^2))`. The shared contracts begin again at
exact-bin source amplitudes and the subsequent harmonic/noise z-score sequence.

Participant z maps then enter the existing group aggregation, clustering, ROI, lateralization, prepared-payload, and manifest stages. Renderer and importer payload schemas remain unchanged unless implementation evidence requires a versioned additive field.
Multi-group projects must create separate group-by-condition summaries and cluster inputs; canonical groups must never be silently pooled.

### Failure and migration behavior

- Failure to write a source-ready derivative does not invalidate an otherwise successful Excel export; it produces explicit source-readiness status.
- Participants with partial canonical conditions or an explicitly incomplete
  source derivative are source-ineligible and omitted from every source
  condition. The prepared manifest, participant sidecar, validation report,
  progress status, and structured log record each omission and reason.
- The retained source cohort remains strict: missing/corrupt derivatives that
  claim to be complete, mixed fingerprints, invalid groups, incompatible
  channels/bins, or zero eligible participants still stop generation.
- Source generation depends on frequency QC/harmonic selection and valid time-domain derivatives, not on successful Stats-ready workbook creation alone.
- Older projects may later receive an explicit backfill action from a valid preprocessed-Raw cache. In this phase, missing derivatives prompt normal reprocessing; amplitude workbooks are never an implicit fallback.
- Projects that already contain valid signed source-ready FIF/JSON derivatives
  do not need sensor reprocessing for these orientation changes. Rebuild the
  source maps to produce the new method identities and caches from the existing
  derivatives.
- Incremental participant reprocessing removes/replaces only that participant's source-ready outputs. Reprocess-all keeps the existing generated-source cleanup behavior.

## Planned Implementation

1. Document the method boundary and intentional Toolbox adaptations.
2. Add a GUI-neutral, project-root-confined derivative writer with atomic FIF/JSON publication and focused round-trip tests.
3. Integrate derivative publication and separate source-readiness state into participant processing without changing the locked preprocessing sequence or existing Excel formats.
4. Add a manifest validator/loader and a reusable opaque fsaverage inverse-model bundle inside `source_producers`.
5. Add the Hauk-informed source-PSD numerical producer with exact-bin validation and deterministic unit tests.
6. Add project orchestration, bounded cache keys, prepared-output export,
   progress reporting, default cortical-normal method identity
   `l2_mne_hauk_source_psd_cortical_normal_v1`, and explicit historical
   `l2_mne_hauk_source_psd_v1` reproduction under
   `6 - Source Localization/L2-MNE Hauk Source PSD Beta`.
7. Add the independent volume inverse, precomputed-volume payload adapter, and
   corrected method identity `eloreta_volume_hauk_source_psd_vector_norm_v1`
   under `6 - Source Localization/eLORETA Hauk Source PSD Beta`, while reusing
   only the shared signed-FIF/cohort/bin/statistical contracts and retaining the
   prior method ID as historical/legacy.
8. Make normal builds generate and load both source-PSD methods while retaining legacy prepared-output import and explicit labeling.
9. Update focused architecture/user method reporting and run processing, project-I/O, LORETA, GUI non-Qt, protected-boundary, and precommit verification.

## Verification and Acceptance

- Exported FIF values equal the arithmetic mean of signed repetition epochs after reload.
- Phase/polarity, volts, EEG ordering, sample frequency, exact `N`, digitization, and reference state survive round trip.
- Every derivative and manifest path remains under the active project root; interrupted publication is not accepted as complete.
- After explicit complete-case eligibility filtering, the producer rejects
  missing/nonfinite retained inputs, incompatible channel/bin contracts,
  nearest-bin substitutions, mismatched retained participant sets, and
  stale/corrupt checksums with actionable errors.
- Frozen-array tests lock harmonic alignment, sum-before-z-score, Toolbox offsets, min/max removal, and population SD.
- Direct-MNE fixtures verify that L2 calls `compute_source_psd` with
  `method="MNE"` and `pick_ori="normal"` by default, while eLORETA calls
  `apply_inverse` with `method="eLORETA"` and `pick_ori="vector"`; both preserve
  the derivative sampling/bin contract and apply their declared amplitude
  conversion or vector pooling.
- Frozen tests verify exact complex periodic-Hann coefficients, the
  `sqrt(sum(abs(Cxyz)^2))` vector norm and rotation invariance, plus identical
  downstream exact-bin/harmonic/z-score arithmetic once method-specific source
  amplitudes have been obtained. They do not imply that real L2-MNE and
  eLORETA arrays are interchangeable.
- Existing source aggregation/cluster/prepared-payload behavior remains covered.
- The existing amplitude-derived manifests still import but are presented as legacy/exploratory.
- No retired source-localization path, bundled fsaverage tree, MEG branch, individual-MRI workflow, or `project.json` source state is introduced.
- Local verification remains non-GUI. A visible/manual Source Map rebuild path is documented for final handoff; pytest-qt remains CI-only.

## Progress Log

- 2026-07-15: Published the previous processing-cache-reset changes as commit `6c08c83` on `codex/condition-aware-qc-speedup`.
- 2026-07-15: Created `codex/hauk-source-psd` from the published commit.
- 2026-07-15: Baseline LORETA focused verification passed (175 tests plus source-boundary, GUI-import, and path audits).
- 2026-07-15: Locked EEG-only fsaverage scope, project-selected harmonics, and the intentional Toolbox frequency-bin rule.
- 2026-07-15: Implemented signed participant-condition time-domain derivatives, atomic manifests, processing-ledger invalidation, and strict project-input validation.
- 2026-07-15: Implemented the EEG-only fsaverage MNE source-PSD producer, exact-bin harmonic/noise alignment, participant cache, validation report, prepared payloads, worker orchestration, and normal-rebuild GUI integration.
- 2026-07-15: Verified the native MNE 1.9.0 `ico3` path end to end with 1,284 fsaverage sources; the loose-orientation inverse remains native while the renderer descriptor is reduced to one orientation norm per source.
- 2026-07-15: Hardened cohort handling so stale ledgers, failed participants, partial condition sets, and mixed project groups cannot silently alter source inference.
- 2026-07-15: Completed focused numerical, processing, project-I/O, static GUI-worker, documentation, boundary, and repository audits; the repository precommit gate passed with 859 tests and 2 skips. Local interactive Qt smoke testing remains deferred to the visible/manual path.
- 2026-07-16: Reconciled processing partial-condition behavior with source
  orchestration: source-ineligible participants are now omitted complete-case
  from all conditions with durable warnings, while the retained derivative
  matrix stays strict. Hardened Windows long-path containment so equivalent
  `D:\...` and `\\?\D:\...` spellings do not falsely reject project-local
  source-ready outputs. Focused LORETA, processing, project-I/O, and GUI gates
  passed; repository precommit completed with 863 tests passed and 2 skipped.
- 2026-07-16: Migrated eLORETA to an independent time-domain source-PSD path.
  The normal rebuild now generates both cortical L2-MNE and volume eLORETA from
  the same validated signed FIF cohort and exact FPVS bin plan. eLORETA retains
  its own inverse, cache, participant arrays, aggregation, and volume-adjacency
  cluster mask; legacy FullFFT manifests remain importable but are not fallback
  inputs.
- 2026-07-16: Versioned source-orientation behavior. L2-MNE now defaults to the
  Hauk-closer cortical-normal estimator with a GUI-selectable historical pooled
  mode. eLORETA now preserves complex exact-bin coefficients through a vector
  inverse and uses a rotation-invariant three-component norm. New method IDs and
  cache provenance prevent either result from being confused with historical
  basis-dependent outputs; existing signed derivatives can be rebuilt without
  reprocessing.

## Deferred Work

- Alternative phase-sensitive estimators beyond the current exact-bin complex
  vector eLORETA path.
- MEG, individual MRI, participant-specific forward models, and coregistration.
- GUI configuration for arbitrary presentation rates, oddball rates, and sinusoidal contrast modulation.
- Cooperative cancellation within an individual native MNE source-PSD calculation; current progress is reported between participant-condition units.
- Cross-version parity testing against a frozen Hauk/MNE reference environment when a shareable reference fixture is available.
