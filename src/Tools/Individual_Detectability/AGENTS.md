# Individual Detectability

Inherit the root and `src/AGENTS.md` rules. Keep the existing summed-harmonic
Z, one-tailed BH-FDR, figure formats, and projectless behavior unchanged.

Managed input selection belongs to `project_coverage.py`; `worker.py` binds
the request before source prevalidation or output writes. Use the public
project dataset index for participant/recording/condition identity and the
current processing-owned FullFFT provenance and QC-20/QC-21 final release.
Final coverage may retain source evidence for an explicitly excluded cell;
that evidence does not authorize analysis. Keep explicit excluded paths
separate from absent coverage. Apply saved cohort exclusions and the user's
participant checkboxes before source reads, cache lookup, or rendering.
Retain every other selected path only after exact canonical identity,
FullFFT source membership, and final source coverage checks; never silently
intersect the selected inputs with an available-file list.

Managed rendering uses the frozen canonical participant identity. Its cache
identity includes that identity plus the source evidence and final release
fingerprints. Refreshing inputs must resolve the current release again; a
previously cached excluded recording cannot re-enter a figure.

Run the headless `tests/processing/test_individual_detectability_core.py`,
`test_individual_detectability_project_coverage.py`, and
`test_individual_detectability_managed_inputs.py` modules for this contract.
Qt execution remains CI-only. The visible smoke path is: open a managed
project with an accepted participant or visit/condition exclusion, generate
Individual Detectability, confirm only retained files appear, then exclude an
additional participant using the checkbox and repeat. An unrelated stale or
unreleased selected workbook must produce an input error before exports.
