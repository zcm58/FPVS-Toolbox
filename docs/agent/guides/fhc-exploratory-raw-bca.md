# Exploratory raw BCA on a completed FHC domain

`scripts/manual_diagnostics/fhc_exploratory_raw_bca.py` uses method identity
`exploratory_native_bca_primary_fhc_domain_v2`. It is an explicit,
source-immutable companion to a completed native `fhc_analysis_families_v2`
run. It is outside the published Hermann-compatible normalized-SNR profile.
It never selects a domain or substitutes standard selected harmonics.

Run the primary native analysis first. If automatic selection finds no eligible
harmonics, report that outcome; there is no primary domain for this companion.
When sharing a machine with preprocessing benchmarks, serialize this analysis
after the benchmark to preserve meaningful runtime and RAM measurements.

Pass absolute paths for the source checkout, managed project, and completed
primary run. The optional output parent must resolve beneath the same project.
For example, with these paths supplied by the caller:

```powershell
python scripts/manual_diagnostics/fhc_exploratory_raw_bca.py `
  --repo-root $sourceRoot --project-root $projectRoot `
  --primary-run $primaryRun --run-id exploratory-raw-bca-01
```

`--prepare-only` still validates and reads scientific inputs, but exports raw
participant tensors without permutation inference. `--wait-seconds` waits for
the exact named primary manifest to appear; it cannot recover a failed primary
analysis. Completed output folders are additive and cannot be overwritten.

The adapter verifies every primary artifact, canonical plan identity, current
neutral FullFFT provenance, adjacency, participant order, and required source
identity. It reconstructs every primary analyzed normalized-SNR tensor from
the original FullFFT inputs before inference. Workbook/native anchors and
authoritative spectral and condition-metric companions are hashed before and
after preparation and again before publication. A changed input aborts
publication. The primary-manifest checksum identifies the exact parsed bytes.

The secondary metric is exact stored native Toolbox `BCA (uV)` at the primary
FHC harmonic columns. This table contains processing-owned per-target values,
independent of the standard selected-harmonic list and Summed-BCA derivatives.
The authoritative condition-metric NumPy companion supplies those values when
declared. Negative finite values and their float64 representation are retained;
there is no BCA recalculation, harmonic summation, or L2 normalization.

The native `qc14_fixed_bin_metrics_v1` producer uses the exact neighboring
offsets -10 through -2 and +2 through +10, removes one finite minimum and one
maximum even when tied, and subtracts the mean of the 16 retained original-order
bins from the target amplitude. Processing calculates BCA independently for
each FFT input and then averages those already-calculated BCA values. Trimming
is nonlinear: recalculating BCA from the averaged FullFFT can produce different
values. The adapter preserves the stored native average. The primary physical
noise window remains in use only for the primary SNR reconstruction check.

Every primary harmonic must have an exact stored column, finite values, current
spectral eligibility, and available native per-input/sensor/harmonic BCA status.
Noise support, retained-bin count, grid, target identity, and eligibility
fingerprints must agree. An unavailable or incomplete required cell fails the
entire secondary plan. The adapter never changes the primary domain, drops a
participant or node, zero-fills, or substitutes another correction formula.

Visit-averaged comparisons average raw BCA over the primary ordered complete
visit pair. Within-group visit contrasts compare the two raw visits. Group
visit-change contrasts subtract raw visit profiles in the primary direction.
Participant inclusion, selected harmonics, directions, sensor adjacency,
seeds, assignment counts, and exact assignment hashes remain those of the
completed primary run.

The existing whole-participant cluster engine supplies signed cluster masses,
raw sign-specific cluster p-values, and the run-global two-sided cluster
p-value. Holm correction uses every frozen comparison within each full family,
with full-plan Holm additionally exported. These exploratory metric families
are separate from the primary SNR families; this does not provide joint
correction across the two metrics. All comparisons, clusters, memberships,
participant identities, raw tensors, null distributions, methods, and source
hashes are exported as CSV/JSON/NPZ with raw-BCA labels. No individual node is
reported as pointwise significant.

Inference is conditional on the primary SNR-selected domain, fixed adjacency,
cluster thresholds, and valid whole-participant exchangeability. The raw-BCA
adaptation and repeated-plan extension are outside the legacy powered-null
calibration. The adapter modifies no project manifest, shared settings,
processed source, participant metadata, ledger, or QC decision. It produces
tables and arrays; native primary FHC retains ownership of publication figures.

Small non-Qt compatibility checks live in
`tests/free_harmonic_clustering/test_exploratory_raw_bca.py` and run against
synthetic native exports, including missing visit pairs and all four supported
families, exact stored native arrays, tied noise, negative BCA, per-input
aggregation, unavailable cells, transposed participant order, and same-size
condition-companion changes. They do not run real study inference.
