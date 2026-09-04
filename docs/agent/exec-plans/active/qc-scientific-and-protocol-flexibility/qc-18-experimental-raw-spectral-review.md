# QC-18: Experimental Raw-Spectral Review

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index and shared contracts. The wave-2
experimental screen uses QC-02, QC-06, QC-11, QC-12's rate/target foundation,
QC-13, QC-15, QC-19, and the project-settings portions of QC-04/QC-17. The
wave-4 deterministic availability step additionally uses finalized QC-12 and
QC-14.

**Status:** accepted on 2026-09-03 and finalized for notch collisions on
2026-09-04. Keep the condition-aware raw-spectral screen as a project-owned
experimental review aid. Retain its current values as provisional defaults;
the screen itself must not exclude or alter data automatically. The configured
notch remains active on overlap, and QC-12/QC-14 deterministically mark affected
standard frequencies or scores unavailable.

## Accepted Behavior

1. Add **Raw spectral artifact screening** to the project's dedicated
   **Experimental settings** section. It is On by default for new projects
   because it is review-only. A missing legacy setting migrates to On to
   preserve current screening. Off records `not_performed_disabled`, does not
   emit a current flag, and cannot reuse prior findings as current evidence.
2. Use brief GUI text: **“Experimental. Flags unusually large narrow-frequency
   signals in each analyzed condition for review. Thresholds are provisional,
   and this check never removes data automatically.”** Help text explains that
   peaks are compared with nearby FFT bins and classified as expected FPVS,
   associated with configured line-noise filtering, or unexpected.
3. Preserve these method-versioned provisional defaults: 0.5-Hz lower bound;
   250 legacy Hann-spectrum score; local-mean ratio 25; local standardized
   score 12; 75% and at least 48 scalp channels for the widespread label; a
   strictly less-than-0.5-Hz notch
   half-width; and the current +/-12-bin neighborhood with target and immediate
   neighbors removed and one finite minimum and maximum trimmed. Label the
   amplitude **Legacy Hann-spectrum score** because the current `2/N` scaling
   omits the Hann coherent-gain correction and is not a correctly normalized
   physical uV amplitude. Do not present the local score as a normal-theory z
   statistic, p-value, or calibrated false-positive probability.
4. Keep the enable control visible and show the effective numerical values
   read-only under **Advanced**. Do not permit numerical editing in the initial
   version. A future calibrated version may add editing with validation and a
   reset control. Keep the FFT scaling and noise-bin recipe locked to the
   method version. Threshold crossings are screening evidence, not validated
   biological cutoffs or proof of artifact.
5. Consume only QC-11/QC-12's canonical project rates, recurrence, and exact
   target grid; QC-13's expected and actual cycle counts; QC-06's exact analyzed
   occurrence spans; QC-15's canonical scalp identity; and the run's effective
   sampling, filter, and notch settings. Never fall back independently to
   6/1.2 Hz. Classify expected peaks by canonical FFT-bin identity with only
   numerical grid tolerance; retire the fixed 0.08-Hz rule from current
   classification because it represents different bin distances at different
   durations. Preserve the old tolerance in legacy provenance. The feature
   must operate consistently for valid nondefault protocols and lengths.
   A valid target below the provisional 0.5-Hz screen boundary is explicitly
   **not evaluated by this experimental screen**; do not claim full protocol
   coverage. Targets and harmonics inside the calibrated domain still use
   canonical bins. Extending the lower boundary requires a new calibrated
   method version.
6. Show review rows by recording, condition, and occurrence, including
   frequency/bin, classification or matched harmonic, channel count/names,
   maximum method score, local ratio and standardized score, widespread status,
   analyzed duration/cycles, and method/threshold version. Default every scientific
   decision to retain. A later exclusion is an explicit downstream user
   decision with its own scope and reason.
7. Calculate and show every configured notch collision with a base/oddball
   target or one of a standard target's required QC-14 noise bins, even when no
   observed peak crosses 250/25/12. This follows from the filter and exact FFT
   grids, not from observing a large raw peak. Do not disable or move an
   effective notch to protect a stimulation frequency. After preprocessing,
   resolve eligibility from the notch actually applied: a directly notched
   target is unavailable for standard analysis, while a notched required noise
   bin makes that target's BCA/SNR/local-z unavailable. Neither outcome alone
   excludes its recording-condition, and no manual choice can restore an
   attenuated frequency. Preserve pre-notch collision/peak evidence separately.
   Use concise text such as: **“The configured line-noise filter affected this
   FPVS frequency. It is not used in standard analysis; other valid frequencies
   remain available.”**
8. Expected-only and ordinary notch-associated peaks may remain in report
   detail; unexpected peaks and notch collisions must be visible in the
   ordinary GUI review. The deterministic frequency-level unavailability is
   distinct from the experimental screen and has no user override. Adaptive
   selection skips the hole without counting it as a response or failure; a
   fixed/preregistered selection reports an unavailable declared result rather
   than silently changing its list. Technical read or nonfinite-data failures
   remain integrity outcomes. Remove all current and legacy raw-spectral
   authority from recording/condition hard-exclusion paths, including
   widespread findings.
9. Fingerprint the enabled state, thresholds/formula/method version, project
   protocol and exact targets, analyzed bounds/cycles, sample rate and FFT
   spacing, experimental raw-spectral scan endpoint, scalp set/montage,
   requested/effective/skipped notch
   centers, filter settings, occurrence identity, classifications, evidence,
   and user decision. Record the analyzed duration, FFT bin width, and realized
   Hz width of the fixed-bin neighborhood because its behavior changes with
   condition length. Preserve the old 0.08-Hz classification tolerance only in
   legacy provenance. Changed inputs make prior evidence stale. Preserve legacy
   history without interpreting an old machine exclusion as current authority.
   For historical outputs, reconstruct collision eligibility only when the
   applied notch mask, filter bounds, FFT grid, and project rates are trusted;
   otherwise mark the standard frequency result stale and require regeneration.
10. Reports must call the feature experimental, reproduce its effective values
    and method-specific amplitude definition, and state when it was disabled or
    unavailable. Do not claim validated artifact detection until a separate
    calibration supports the intended rates, durations, filters, sampling
    rates, equipment, and populations.

## Owners and Verification

Primary owners are project settings and migration, `gui/settings_panel.py`,
`gui/preprocessing_qc_workflow.py`, `processing/raw_spectral_qc.py`,
`processing/preflight_qc.py`, processing runners/workers, notch-configuration
resolution, QC reporting, and cache/ledger consumers. Use the shared
experimental-settings surface from QC-04/QC-17 and the QC-02 outcome language.
QC-18 remains distinct from QC-17: QC-18 examines raw within-condition spectra
before preprocessing; QC-17 examines summed baseline-corrected analysis values
after processing.

Cover settings migration and round-trip, locked read-only defaults,
Off/not-performed behavior, every
exact threshold boundary, the fixed neighborhood and Hann formula, localized
and widespread patterns, expected/notch/unexpected/collision categories,
50/60-Hz notch configurations and their effective harmonics, direct-target and
noise-bin collisions without an observed peak, notch retention on overlap,
adaptive-hole behavior, fixed-profile unavailability,
technical failures, a valid target below 0.5 Hz reported as not evaluated,
QC-19-approved spans, changed-input staleness, and nondefault rates and cycle
counts. Prove no result changes channel repair, crop, inclusion, or cohort,
including legacy widespread records. Use non-GUI checks, CI-only Qt coverage,
and a documented visible smoke path.

Calibrate the 250/25/12 operating characteristics on annotated BioSemi64 FPVS
data across rates, durations, filters, sampling rates, and artifact types before
strengthening the feature's claims or authority. That calibration must evaluate
a correctly coherent-gain-normalized Hann amplitude; adopting physical uV
requires a new method version and a re-derived threshold rather than merely
renaming the legacy score. Spectral peaks at stimulation harmonics can be
genuine responses, adjacent-bin baselines have FPVS precedent at predeclared
targets rather than as an all-bin artifact classifier, and duration determines
FFT resolution ([Norcia et al., 2015](https://doi.org/10.1167/15.6.4),
[Figueira et al., 2022](https://doi.org/10.1016/j.dcn.2022.101066),
[PREP](https://doi.org/10.3389/fninf.2015.00016),
[SciPy spectral-scaling guidance](https://docs.scipy.org/doc/scipy/tutorial/signal.html#spectral-analysis)).
Update the preprocessing/QC architecture, calibration guidance, user QC guide,
and methods-reporting checklist when this action is implemented.
