# QC-14: Neighboring-Noise Applicability Guard

[Parent QC plan](../qc-scientific-and-protocol-flexibility.md) · [shared execution contracts](00-shared-contracts.md) · [review evidence](review-record.md)

Load this module with the parent index, shared contracts, QC-12's completed
rate foundation, and QC-13 when executing this action. QC-12's replacement
harmonic domains finalize after this applicability boundary is available.

**Status:** core implementation complete on 2026-09-04 with focused numerical
coverage. Ordinary
conditions are expected to be at least about 60 seconds, but validity is
decided from cycles and available frequency bins rather than a fixed duration.

### Implementation Progress

- The canonical spectral resolver requires more than ten realized oddball
  cycles and the exact symmetric candidate offsets `-10..-2,+2..+10`. It
  checks DC, applied high-pass/low-pass edges, Nyquist, tagged project
  harmonics, and effective notch support before exposing a standard metric.
- `compute_qc14_standard_metrics` requires all 18 finite candidate amplitudes,
  removes one actual minimum and maximum occurrence, and retains exactly 16
  values. It reports BCA, SNR, and local-z availability separately, including
  effectively zero mean and population-SD denominator states.
- Post-processing writes unavailable values as missing with structured reason
  codes. A notched target is audit-only; a notch confined to a noise bin keeps
  target amplitude as audit evidence but withholds all standard scores. No
  notch hole excludes a recording-condition.
- Adaptive selection consumes only the shared eligible order sequence, so a
  hole is neither a success nor a failure and the two-failure rule continues
  with the next eligible harmonic. A fixed/preregistered declaration that
  intersects a hole is reported unavailable without changing its list.
- Managed SNR plots intersect the exported eligibility evidence across their
  provenance-allowed workbooks and highlight only technically eligible
  non-presentation harmonics. This is intentionally distinct from the Stats
  profile's selected list.
- Focused tests cover exact 10/11-cycle boundaries, edge and Nyquist clearance,
  notch target/noise collisions, finite completeness, tied-extrema trimming,
  zero/near-zero denominators, common-domain intersection, and unchanged valid
  metric arithmetic.

## Accepted Behavior

1. Preserve the versioned neighboring-noise calculation: inspect target
   +/-10 bins, exclude target-1, target, and target+1, drop one finite minimum
   and maximum, then calculate mean and population SD from the 16 retained
   values. Do not silently substitute a fixed-Hz or smaller/asymmetric window.
2. Before calculating standard BCA, SNR, or local z, require:
   - a complete symmetric set of the 18 candidate offsets `-10..-2` and
     `+2..+10`, leaving 16 finite values after trimming;
   - more than 10 realized analyzed oddball cycles;
   - every target and offset through +/-10 to fall inside the project's applied
     high-pass/low-pass range, with ten-bin clearance from DC and Nyquist; and
   - no target or required candidate bin inside the attenuation support of an
     applied line-noise notch; and
   - no declared presentation/oddball harmonic in any candidate bin.
   After the finite trimmed baseline is formed, require a finite nonzero noise
   mean for SNR and a finite nonzero population SD for local z. Use a
   method-versioned numerical tolerance for values effectively equal to zero.
   BCA may remain available when its source bins are valid even if only the
   SNR or local-z denominator is invalid.
3. Apply availability by failure type. Missing/asymmetric/nonfinite support,
   insufficient cycles, an edge collision, or another tagged harmonic in the
   candidate bins invalidates all affected standard BCA/SNR/local-z results.
   An applied-notch collision with the target also makes that target
   unavailable; a collision confined to a required noise bin invalidates the
   noise-based BCA/SNR/local-z scores while retaining the target amplitude only
   as clearly labeled audit evidence.
   With otherwise valid source/support bins, a zero or effectively zero noise
   mean invalidates SNR only, and a zero or effectively zero noise SD invalidates
   local z only; BCA remains available. Prevent any invalid metric from
   finalizing QC or harmonic selection where that metric is required. Explain
   the exact reason and recommend a longer protocol or future validated method.
   Never compute a partial baseline, fill values, or permit a manual decision
   to make an undefined score valid.
   Keep the notch enabled regardless of base/oddball overlap. Do not count an
   unavailable notched harmonic as an adaptive success or failure, and do not
   exclude the whole recording-condition solely because of the frequency hole.
4. Record analyzed samples/cycles/duration, bin width, +/-10-bin Hz reach,
   candidate and retained bin identities, edge clearance, tagged-frequency
   checks, and method version in workbooks and provenance.
   Treat a legacy artifact without enough trusted protocol/bin provenance to
   prove applicability as stale for this use and regenerate it; do not assume
   that an old numeric value passed the new guard.
5. Keep the fixed-bin rule because it preserves the reference-sample count and
   has FPVS precedent. Before offering fixed-Hz or duration-adaptive modes,
   separately calibrate type-I error and sensitivity across supported rates,
   cycles, filters, and realistic EEG noise. Do not describe the current local
   z threshold as an exact false-positive probability without that evidence.

## Owners and Acceptance

Apply QC-12's one canonical spectral-eligibility resolver to
`Tools/Stats/analysis/noise_utils.py`, active post-processing BCA/SNR/z
calculation, FullFFT provenance/grid QC, and adaptive harmonic selection
without changing valid numerical outputs. Bind the result to QC-11/QC-13
protocol identity and artifact fingerprints; do not independently rebuild a
target list in any consumer.

Cover valid 120- and 60-second protocols, the 3-Hz/every-10 design at 60
seconds, exactly 10 versus 11 cycles, first and highest analyzed harmonics,
DC/Nyquist truncation, another tagged harmonic in the candidate set,
nonfinite bins, zero/near-zero noise mean, zero/near-zero noise SD, separate
BCA/SNR/z availability, unchanged per-target math inside the former 6/1.2-Hz
range, preserved already-generated legacy artifacts, and newly eligible
above-16.8-Hz targets only under the new method version. Update
the post-processing/export, FFT-crop, harmonic-selection, and methods-reporting
contracts. Run focused non-GUI gates; no new GUI surface beyond concise status
and remediation text is required.

Scientific basis: local frequency-noise estimation is appropriate only when
the reference band excludes stimulation harmonics
([Norcia et al., 2015](https://doi.org/10.1167/15.6.4)); analyzed duration and
frequency resolution must be reported
([Keil et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9717489/)).
