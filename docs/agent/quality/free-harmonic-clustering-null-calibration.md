# Free Harmonic Clustering Automatic-Domain Null Calibration

Status: protocol frozen; powered execution complete; reviewed PASS revalidated on 2026-08-18

Protocol: `fhc_automatic_unconditional_null_v1`

This protocol evaluates empirical global-null rejection for the complete
Hermann automatic-domain selection plus cluster-permutation workflow. It is a
separate, explicitly invoked scientific validation study. It is not part of
pytest, focused verification, precommit, or the user-facing application.

The reviewed powered result passed every prespecified guardrail. The durable
completed receipt is
`free-harmonic-clustering-null-calibration-v1-receipt.json`. The separate
pending template remains unchanged and is still not result evidence.

## Two Validation Layers

Routine CI retains the deterministic regression smoke in
`tests/free_harmonic_clustering/test_automatic_null_regression.py`:

- 24 independent-group null replicates;
- 199 assignments per replicate;
- automatic selection rerun for every replicate; and
- at most five global rejections.

That intentionally broad envelope catches gross software regressions. It does
not estimate or establish unconditional familywise error.

The powered layer is the protocol on this page:

- 4,000 null replicates;
- 2,000 independent-group and 2,000 paired-condition replicates;
- four frozen 500-replicate regimes within each design; and
- the production 10,000 assignments in every replicate.

It runs only through
`scripts/manual_diagnostics/run_free_harmonic_clustering_null_calibration.py`.

## Reviewed Powered Result

The 2026-08-18 performance-refactor revalidation completed all 4,000 scheduled
replicates and exactly reproduced the previously reviewed ordered scientific
results and determinism fingerprints. Its overall, powered-null, and
determinism assessments all have status `pass`. There were no missing,
duplicate, unexpected, or invalid task rows, no execution errors, and no
no-selection outcomes.

The two design-level decisions were:

| Design | Global rejections | Rate | Positive / negative | 97.5% upper bound | Critical count | Selected ceilings | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Independent groups | 111 / 2,000 | `.0555` | 60 / 55 | `.06645369553133039` | 117 | 32 distinct, 1-39 | PASS |
| Paired conditions | 91 / 2,000 | `.0455` | 43 / 49 | `.055572191006579195` | 117 | 32 distinct, 1-39 | PASS |

Both exact one-sided 97.5% bounds are below the frozen `.070` design limit.
The independent-groups result is the narrower pass: 111 rejections are six
below the maximum passing count of 117.

The eight design x regime decisions were:

| Design | Regime | Global rejections | Rate | Positive / negative | 95% upper bound | Selected ceilings | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| Independent groups | `iid_two_harmonic_lognormal` | 31 / 500 | `.062` | 18 / 14 | `.08276150904882956` | 31 distinct, 2-39 | PASS |
| Independent groups | `correlated_two_harmonic_lognormal` | 30 / 500 | `.060` | 13 / 17 | `.08050473428435695` | 31 distinct, 2-39 | PASS |
| Independent groups | `threshold_edge_lognormal` | 24 / 500 | `.048` | 14 / 13 | `.06684328408121025` | 32 distinct, 1-39 | PASS |
| Independent groups | `heavy_tail_two_harmonic` | 26 / 500 | `.052` | 15 / 11 | `.0714220697504856` | 31 distinct, 2-39 | PASS |
| Paired conditions | `iid_two_harmonic_lognormal` | 18 / 500 | `.036` | 8 / 10 | `.05291833696978857` | 31 distinct, 2-39 | PASS |
| Paired conditions | `correlated_two_harmonic_lognormal` | 23 / 500 | `.046` | 12 / 11 | `.06454329632416769` | 31 distinct, 2-39 | PASS |
| Paired conditions | `threshold_edge_lognormal` | 29 / 500 | `.058` | 13 / 17 | `.07824266578566919` | 32 distinct, 1-39 | PASS |
| Paired conditions | `heavy_tail_two_harmonic` | 21 / 500 | `.042` | 10 / 11 | `.059919946848314386` | 32 distinct, 1-39 | PASS |

Every cell completed 500 replicates with zero errors and zero no-selection
outcomes. Every exact one-sided 95% bound is below the frozen `.10` cell limit,
and every cell is below the maximum passing count of 38. Positive and negative
counts need not sum to the global count because one replicate can reject in
both tails.

### Reviewed Artifact And Execution Identity

The completed receipt has SHA-256
`710beea7455e9987ddcaa68570872a1f88db1c21fe451726b27608825d2a9a4f`.
Its canonical ordered scientific-results fingerprint is
`1e5444baec5faabc18a286167de82208a811f83e5aab3eb9bf92bdaac803d448`.
The serial, resumed, and parallel non-official determinism checks all produced
`1d6e59ca6f2ce1d964edd89543cac89d620f38c394776fa873b965e201f75808`.

The reviewed local output also had these raw byte hashes:

| Output | SHA-256 |
| --- | --- |
| `protocol.json` | `6dd8420978d7cdb4dd7c63f6b34e4c4aadce0c7992b8359ec1c60ec0aea526c3` |
| `receipt.json` | `710beea7455e9987ddcaa68570872a1f88db1c21fe451726b27608825d2a9a4f` |
| `results.jsonl` | `a35677c9bd6f6a51ffdda98c9ba107ead56524e9f25ba86a7cf29230cc90d6c5` |

The raw checkpoint hash includes elapsed timings. The receipt's ordered-results
fingerprint excludes elapsed time and is the scientific identity intended to
match across serial, resumed, and parallel execution.

The run used toolbox commit
`753d44a8e6f28ac342a04cb3c95132022d3b793d`, Python `3.13.9`, NumPy `2.3.1`,
SciPy `1.16.0`, platform `Windows-11-10.0.26200-SP0`, and 32 workers. The
reviewed scientific source hashes were:

| Source | SHA-256 |
| --- | --- |
| `scripts/manual_diagnostics/run_free_harmonic_clustering_null_calibration.py` | `0e66e587beae8347a7783edcf9c4fddc0cd0662df6d54440a192861313daa904` |
| `src/Tools/Free_Harmonic_Clustering/analysis.py` | `d22e0cdabc4c4fed384420081238cdef7cad6b0a88302e35a844b20f0324b961` |
| `src/Tools/Free_Harmonic_Clustering/models.py` | `bb793ccad27fb9872e33406d1ba525a17fdd1ca9db69a0bf71e352bae6f4d213` |
| `src/Tools/Free_Harmonic_Clustering/null_calibration.py` | `e7bf7eb7e87dc1873af8733f8073bcab7a194a618ea8574c07588281cc4c1dce` |
| `src/Tools/Free_Harmonic_Clustering/preparation.py` | `a41151267d89f88320cfb30e40c2ec3ec065947991fee9f2294d284dbd3535cc` |

The recorded protocol fingerprint remains
`178739203fc5fd32702681546cae9ad50d153b79c850921531aee8410a585936`.

### Interpretation Limits

This PASS supports the complete adaptive selection plus cluster-permutation
workflow only for the frozen designs, generators, sample sizes, adjacency, and
numerical settings under the prespecified `.070` design and `.10` regime
limits. It is not mathematical proof for arbitrary data-generating processes,
does not establish power under non-null effects, and does not mean that every
observed rejection rate must be below `.05`. The determinism assessment is a
two-task, 19-assignment execution-mode check, not a second powered run. The
receipt contains the exact source and runtime identity but no completion
timestamp or command line.

## Frozen Numerical Method

Every replicate uses the current
`hermann_free_harmonic_clustering_cleanroom_v2` automatic method:

- oddball rate 1.2 Hz and base rate 6 Hz;
- full 48 Hz candidate domain at 0.025 Hz resolution;
- automatic grand-arm harmonic threshold `z > 3.29`;
- dynamic base-rate-overlap exclusion;
- cluster-entry alpha `.01`;
- raw per-tail cluster alpha `.025`;
- 10,000 whole-participant assignments sampled with replacement; and
- the fixed 197-edge
  `biosemi64-fieldtrip-style-compressed-cleanroom-v1` adjacency.

A global rejection means that a replicate produces at least one significant
positive or negative cluster. Positive and negative rejections are also
reported separately.

## Designs And Null Regimes

The independent design uses 18 versus 16 participants. The paired design uses
18 participants observed in both arms. Both arms receive the same population
FPVS signal, so the contrast null is true. Paired simulations share 60% of the
latent field between arms; independent arms are generated independently from
the same distribution.

| Regime | Positive-amplitude generator | Common target boosts | Dependence |
| --- | --- | --- | --- |
| `iid_two_harmonic_lognormal` | lognormal, log scale `.18` | H1 `2.0`, H2 `1.35` | none |
| `correlated_two_harmonic_lognormal` | lognormal, log scale `.18` | H1 `2.0`, H2 `1.35` | sensor smoothing `.35`, physical-bin frequency AR `.55` |
| `threshold_edge_lognormal` | lognormal, log scale `.18` | H1 `.08`, H2 `.016`, H3 `.012`, H4 `.008` | sensor smoothing `.20`, physical-bin frequency AR `.30` |
| `heavy_tail_two_harmonic` | clipped exponentiated standardized Student-t, df `5`, log scale `.20` | H1 `.50`, H2 `.20` | sensor smoothing `.20`, physical-bin frequency AR `.30` |

The complete automatic selector is rerun from each replicate's two grand-arm
spectra. Participant SNR, L2 normalization, and production cluster inference
then run on that replicate's selected domain. A no-selection replicate is
recorded as a non-rejection and a separate analyzability failure; it cannot be
silently omitted.

Frequency AR coefficients are defined per `.025`-Hz physical FFT-bin step.
The bounded-memory generator advances directly between retained columns using
`rho ** physical_bin_gap`, which is equivalent to generating the intervening
uniform-grid AR process and then selecting the required columns. It does not
treat separated noise windows as adjacent samples.

## Seeds And Freeze Boundary

Data and permutation seeds are independent deterministic uint32 values derived
from SHA-256 over protocol ID, design, regime, and replicate index. Python's
process-randomized `hash()` is never used. Serial, resumed, and parallel runs
must therefore produce the same ordered scientific-result fingerprint; elapsed
timings may differ.

The generator, seeds, rejection definition, and acceptance envelope are frozen
before any powered permutation outcome is inspected. A selection-only pilot
with disjoint seeds may establish that a proposed future protocol exercises an
adaptive domain, but it must not compute cluster rejections. Any change after a
powered outcome is inspected requires a new protocol ID and a new receipt.

The frozen protocol fingerprint is
`178739203fc5fd32702681546cae9ad50d153b79c850921531aee8410a585936`.
The generator/receipt implementation version is `1.1`; the completed runtime
receipt hashes the five scientific/execution source files. The first invocation
stored those hashes plus exact Python, NumPy, SciPy, and platform identities in
`protocol.json`; every resume had to match them before a checkpoint row was
accepted. Loaded rows also had to match their scheduled task metadata and both
deterministic seeds.

## Prespecified Acceptance Envelope

All guardrails must pass:

1. For each design, the one-sided 97.5% exact Clopper-Pearson upper bound on
   global rejection must be below `.070`. With 2,000 replicates this permits at
   most 117 rejections: 117 gives `.069699`; 118 gives `.070240`.
2. For each design x regime cell, the one-sided 95% exact Clopper-Pearson upper
   bound must be below `.10`. With 500 replicates this permits at most 38
   rejections: 38 gives `.098428`; 39 gives `.100650`.
3. All 4,000 task IDs must be present exactly once, with no execution errors or
   no-selection outcomes, and every regime must exercise at least two selected
   ceilings.
4. Two disjoint, non-official 19-assignment tasks must have identical scientific
   rows and ordered fingerprints under serial, checkpoint-resumed, and process-
   parallel execution. This check runs before powered scheduling and its three
   fingerprints are recorded in and enforced by the final assessment.

At a true design-level error rate of `.05`, the design rule passes with
probability about `.961`. At the unacceptable `.070` boundary it passes with
probability about `.022`, providing about 97.8% power to detect that boundary
within each design. The two 97.5% one-sided bounds provide a Bonferroni family
confidence of at least 95% across the paired and independent design decisions.

The envelope must not be tuned after results are known. If a guardrail fails,
report the failure and either change the automatic method/default with a new
method and protocol version or retain an explicitly exploratory/conditional
interpretation. The 24 x 199 smoke cannot substitute for this decision.

## Running And Resuming

Choose a dedicated output directory explicitly; the runner never reads or
writes a managed FPVS project:

```console
python scripts/manual_diagnostics/run_free_harmonic_clustering_null_calibration.py \
  --output-dir .codex-tmp/fhc-null-calibration-v1 \
  --workers 8
```

The selected output directory is the calibration output root. It receives:

- `protocol.json`, which prevents cross-protocol, cross-source, or cross-runtime
  resume;
- `results.jsonl`, atomically rewritten in deterministic task order; and
- `receipt.json`, written only when all 4,000 tasks are present.

Use `--max-new-replicates N` for bounded sessions and rerun the same command to
resume. Worker count does not enter scientific seed derivation. Raw checkpoint
rows may remain in the ignored local output directory; a reviewed compact
receipt and its raw-results fingerprint are the durable evidence.

## Receipt And Invalidation

The pending schema/protocol template is
`docs/agent/quality/free-harmonic-clustering-null-calibration-v1-receipt-template.json`.
It has `status: pending`, no assessment, and must never be cited as a result.
It remains unchanged. The separately reviewed completed result is
`docs/agent/quality/free-harmonic-clustering-null-calibration-v1-receipt.json`;
it has `status: complete` and assessment status `pass`.

Invalidate and rerun the powered calibration after a change to automatic
selection, SNR/L2 preparation, cluster construction or p-values, default
candidate domain, permutation assignments, method version, or adjacency. Pure
GUI, export-format, and explanatory-copy changes do not invalidate it.

Even a passing receipt supports only these frozen simulated regimes and bounds.
It is not mathematical proof of unconditional error control for every possible
data-generating process.
