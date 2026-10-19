# Brain Products processing support

Branch: `codex/brain-products-support`, based on `codex/v3.0.1-release`.

## Scope and acceptance

- Persist a confirmed acquisition hardware choice per project. Preserve legacy
  BioSemi projects; require an explicit warning before changing a configured
  platform. File detection supplies evidence, never silently changes hardware.
- Read BrainVision Core Data Format and BrainVision Recording Format using
  documented units, companion files, channel roles, and marker semantics.
- Route recordings through shared discovery, preflight, processing, and exports.
  Recording identity and cache freshness include required companion files.
- Resolve reference, retained channels, geometry, and supported QC operations
  from explicit acquisition policy. Preserve the locked BioSemi sequence and
  legacy fingerprints. Do not invent positions or assume 64 channels.
- Keep spatial methods restricted to their qualified montage. Hardware-family
  support does not establish amplifier calibration or physical trigger latency.
- Provide a future Studio hardware-evidence boundary without claiming that the
  currently documented Studio interchange already supplies that field.
- Add focused unit/integration coverage and CI-only GUI confirmation coverage;
  run local non-GUI gates and document visible acceptance steps.
- Commit and push the feature branch; do not merge main or publish a release.

## Work areas

Reader adapters, project/settings GUI, and acquisition pipeline are developed
in parallel with shared contracts. Integration owns discovery, preflight/cache
provenance, export compatibility, documentation, and final verification.

## Progress

- [x] Base branch fetched; feature branch created with a clean working tree.
- [x] Relevant boundary, path, and GUI audits passed before edits.
- [x] Reader adapters and synthetic source-format fixtures.
- [x] Project persistence, confirmation, and change warning.
- [x] Pipeline, discovery, cache, and export integration.
- [x] Focused regression coverage, compatibility fixes, and documentation.
- [ ] Release acceptance with representative laboratory recordings and visible GUI checks.

## Verification evidence

- Generated BVCDF and BVRF recordings exercise calibrated reads, stimulus
  semantics, preflight scanning, FIR/resampling/reference, crop/FFT, spectral
  exports, source derivatives, cache restoration, and threaded prefetch.
- Recorded coordinates and explicit template coordinates retain separate
  provenance. A 64-channel fixture with custom labels verifies that exports do
  not rename Brain Products electrodes as BioSemi electrodes.
- Companion changes invalidate identities without requiring a changed header.
  Invalid hardware selections fail before loading or cache reuse, and failed
  role/montage validation releases owned Windows memory maps.
- Qt confirmation, persistence, cancellation, capability messaging, and layout
  coverage are registered for CI. No local Qt execution was performed.
- Spectral cohort provenance preserves individual electrode coordinates with
  shared channel/policy validation. Fixed and adaptive Stats-ready exports retain
  valid ROI values and explicitly mark unrecorded template ROIs unavailable.

This plan remains active until representative laboratory recordings and the
visible acceptance path are checked before merging into the release branch.

## Visible acceptance path

Create a project from each supported header format, confirm Brain Products,
configure the recorded montage/reference, process a recording, and inspect the
participant/condition exports. Close and reopen the app and confirm the saved
hardware choice. Cancel a hardware change and verify unchanged settings; accept
the warning and verify that previous processing is not reused. Repeat with an
existing BioSemi project. With Brain Products selected, confirm that automatic
source-map phases are skipped while compatible spectral and statistical tables
complete. Try LORETA, Scalp Maps and Free Harmonic Clustering: each action should
show one unsupported-montage message without opening its analysis page. Ordinary
nonspatial tool actions should remain available. GUI execution remains CI-only until a safe visible
local environment is explicitly approved.
