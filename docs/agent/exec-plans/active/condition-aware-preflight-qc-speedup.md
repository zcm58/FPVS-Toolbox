# Condition-Aware Preflight QC Speedup

## Goal

Reduce the embedded data-quality-check latency and memory footprint without
changing the continuous preprocessing pipeline, its 256 Hz downsample target,
its filter order, or any generated scientific output.

## Locked Decisions

- The normal preprocessing path remains unchanged and continues to load the
  complete selected BDF channel set before the locked FIR, optional smart FFT
  multi-notch, and 256 Hz downsample stages.
- Preflight QC v2 reads the complete Status channel, but reads EEG samples only
  from configured condition-onset through condition completion. Samples outside
  configured conditions are not scored.
- Condition completion is at least the configured epoch end and extends through
  the exact locked FFT span when normal processing will use a longer interval.
  It does not follow a discontinuous oddball-marker stream beyond that crop and
  never crosses the next configured condition onset or recording end.
- Time-domain QC examines every sequential 10-second block plus the final
  partial block in every relevant condition occurrence.
- Only channels flagged consistently across every relevant condition occurrence
  are prefilled as persistent removed-electrode candidates; occurrence-specific
  and transient-block findings remain separately reported review signals.
- Spectral QC reuses the locked FPVS on-bin crop planner and the common
  integer-oddball-cycle length used by normal processing. It does not use an
  arbitrary 90-second prefix.
- Long condition buffers spill to a temporary condition-only float64 memmap in
  10-second read chunks; the complete recording is never mapped for preflight.
  FFT channels are batched with byte-identical per-channel results so temporary
  memory stays bounded.
- Spectral candidates extend through the configured retained upper band, bounded
  by the source-data and configured 256 Hz target Nyquist limits. The sampling
  rate remains 256 Hz; 128 Hz is only its Nyquist frequency.
- Spectral neighboring noise uses the shared Stats helper with an explicit
  +/-12-bin window. The target and immediately adjacent bins are excluded,
  leaving 22 candidates; one global minimum and maximum are removed, leaving
  20 bins for the mean and population standard deviation.
- Configured effective 50/60 Hz mains-notch centers and their harmonics are
  classified separately from unexpected off-harmonic peaks. A mains/FPVS
  harmonic collision is recorded explicitly.
- New exhaustive/transient preflight findings are review signals. This speedup
  does not silently create new automatic hard-exclusion rules.
- Cache state lives only under the active project root at
  `.fpvs_processing/preflight_qc/v2`, is written atomically, and treats missing,
  corrupt, or stale entries as cache misses.
- The v2 fast path requires an explicit active project root and complete event
  map. The existing preflight API remains a compatibility fallback when those
  inputs are absent.
- QC concurrency is bounded independently from processing concurrency: at most
  four participant workers, two simultaneous BDF reads, and two simultaneous
  spectral evaluators.

## Phases

1. Extract and regression-test the shared per-condition common FFT-span planner.
2. Add an opt-in lazy, context-managed BDF reader through
   `Main_App.io.load_utils` while retaining the eager loader unchanged.
3. Add condition-span planning plus exhaustive time-domain and on-bin spectral
   QC engines with deterministic focused tests.
4. Integrate project-local cache, bounded concurrency, cancellation checkpoints,
   timing logs, and truthful participant/condition progress.
5. Update the preprocessing/loader/GUI contracts and run processing,
   project-I/O, GUI-static, protected-boundary, and repo precommit gates.

## Progress

- [x] New branch `codex/condition-aware-qc-speedup` created.
- [x] Shared FFT-span planner extracted and normal runner parity verified.
- [x] Lazy preflight-only BDF reader implemented without changing eager loads.
- [x] Versioned project-local cache primitive implemented and path-audited.
- [x] Condition-aware engines and orchestration integrated.
- [x] GUI progress/cancellation integration completed.
- [x] Documentation and full verification completed.

## Verification Notes

Do not run Qt or offscreen GUI tests locally. Register any needed pytest-qt
coverage for CI, run the safe GUI-static gate locally, and document a visible
Windows smoke path.
