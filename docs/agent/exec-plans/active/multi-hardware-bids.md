# Multi-hardware BIDS admission

Branch: `codex/multi-hardware-bids`, based on `b6dd6101`.

The maintainer requested processing through the BIDS adapter for Brain Products,
BioSemi ActiveTwo, BioSemi ActiveThree and Unicorn mobile EEG. BrainProducts is
the same manufacturer as Brain Products. This work extends acquisition adapters
and persisted project choices; shared numerical stages must remain generic.

## Contracts

- Preserve existing ActiveTwo BioSemi64 and Brain Products numerical outputs,
  method order, serialized fingerprints and project settings.
- ActiveThree has an explicit identity and recording-owned geometry. Its BDF
  format is documented as unchanged; channel count and cap/reference policy
  cannot be inferred from the extension. Do not enable calibrated BioSemi64 QC
  for arbitrary layouts.
- Unicorn uses the existing explicit `unicorn_hybrid_black` acquisition profile:
  raw classic BDF or continuous BDF+, eight declared scalp electrodes, native
  250 Hz, eight-scalp average reference, no resampling or interpolation. Reject
  discontinuous files, ambiguous labels, invalid units and unsupported timing.
  Preserve repeated adjacent markers with sample-wise decoding. Recorded
  annotations require explicit event interpretation.
- Keep originals unchanged. Project-local BIDS imports retain source identities;
  reviewed Unicorn unit-header normalization is recorded and originals preserved.
  BVRF retains its documented lossless FIF64 derivative exception.
- Persist hardware and mapping choices per project, require explicit confirmation
  to change hardware, and do not infer a BDF manufacturer from its suffix.
- Synthetic format/pipeline success is software acceptance, not validation of
  physical amplitude, reference wiring, wireless loss behavior or stimulus latency.

## Work and validation

- [x] Extend project choices, persistence and existing settings controls.
- [x] Extend upstream geometry and immutable processing contracts.
- [x] Route all four systems through shared BIDS admission and loading.
- [x] Preserve canonical event samples across preflight, processing and exports.
- [x] Run focused format/loading/failure tests and end-to-end processing matrix.
- [x] Recheck ActiveTwo exact old/new outputs with optional QC off.
- [x] Update current-state docs, source references and validation receipt.

No local Qt/offscreen execution or broad repository scientific suite. Use
generated fixtures and focused non-GUI tests. Visible follow-up: select each
hardware choice in an isolated project, save/reopen, verify hardware-change
warning and mapping/reference controls, then process a small supported recording.

## Primary references

- [BioSemi ActiveThree FAQ](https://www.biosemi.com/faq/All_questions_about_the_Active3_system.htm)
- [ActiveThree specifications](https://www.biosemi.com/ad-box_activethree.htm)
- [BioSemi BDF format](https://www.biosemi.com/faq/file_format.htm)
- [Unicorn Recorder manual](https://github.com/unicorn-bi/Unicorn-Recorder-Hybrid-Black/blob/main/README.md)
- [Unicorn hardware manual](https://github.com/unicorn-bi/Unicorn-Suite-Hybrid-Black-User-Manual/blob/main/UnicornHybridBlack.md)
- [EEG-BIDS specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html)

The existing [Unicorn plan](unicorn-hybrid-black-support.md) retains source-specific
acquisition evidence and unresolved physical qualification questions.

## Acceptance evidence (2026-10-19)

- [Portable hardware matrix receipt](../../../../scripts/manual_diagnostics/receipts/multi_hardware_bids_20261019.json):
  10 generated hardware/format cases, 20 cold/warm processing runs, all exports
  complete and warm caches reused. Two additional fixtures preserve adjacent
  markers and all codes 1–255. The matrix plus acquisition contracts passed
  35 tests in 17.86 s. Existing float32 cache roundoff is assessed separately
  from exact BIDS preservation and has explicit bounds in the receipt.
- [Five-participant ActiveTwo regression](../../../../scripts/manual_diagnostics/receipts/multi_hardware_biosemi_equivalence_20261019.json):
  QC off, compared with pre-BIDS `da14edaa`; 35 files checked, 30 scientific
  files byte-identical, 415 arrays and 5,375,645 values exactly equal.
  Maximum numeric difference 0. BIDS conversion 0.749587 s; complete preparation
  1.450421 s; old processing 23.823494 s and new processing 23.385223 s.
  Import/provenance additions explain the remaining metadata differences.
- Focused settings, format/unit, event, cache, pipeline and export regressions
  passed. Canonical markers are validated before integer conversion and bound
  to their native grid and import/cache identity. Corrupt import evidence is
  rebuilt; cache restoration fails closed.
- Strict documentation build and all repository invariant audits passed.
  Qt coverage was added for CI; no local GUI or repository-wide scientific
  suite was run. The visible smoke path above remains human acceptance work.

Physical acquisition calibration, complete Studio handoff, additional cap/sensor
configurations, and unqualified spatial tools remain outside this acceptance.
Unicorn's nonidentity-scaled telemetry is retained as explicitly unverified;
synthetic continuity checks do not establish wireless loss detection.
