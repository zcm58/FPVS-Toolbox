# Individual Detectability

Inherit the root and `src/AGENTS.md` rules. Keep the existing summed-harmonic
Z, one-tailed BH-FDR, figure formats, and projectless behavior unchanged.

The [shared hardware and Studio roadmap](../../../docs/agent/architecture/hardware-pipeline-studio-roadmap.md)
governs future montage support. Consume shared acquisition/montage identities
and qualified ROI coverage rather than adding local hardware detection or
silently intersecting electrode sets. Import compatibility alone does not
qualify the existing detectability method for a new recording context.

Managed input selection belongs to `project_coverage.py`. The Qt-free
`export_run.run_detectability_export` binds the request, prevalidates all
selected conditions in managed runs, then writes metadata, logs and figures.
`worker.py` adapts its callbacks, return value and exceptions to the desktop
signals. All-excluded runs complete successfully with an explanatory log.
Use the public
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

The Run card keeps progress and wrapping status visible. View Generation Log
opens the full live log in a dialog and preserves history when dismissed.

Run the headless `tests/processing/test_individual_detectability_core.py`,
`test_individual_detectability_project_coverage.py`, and
`test_individual_detectability_managed_inputs.py` modules for this contract.
Qt execution remains CI-only. The visible smoke path is: open a managed
project with an accepted participant or visit/condition exclusion, generate
Individual Detectability, confirm only retained files appear, then exclude an
additional participant using the checkbox and repeat. An unrelated stale or
unreleased selected workbook must produce an input error before exports.
At the shared workspace size, check that the Advanced harmonic controls, SNR
and layout forms, and parameters summary fit with the custom-harmonics warning
visible. Open and close View Generation Log while a run is active, then reopen
it and verify that the complete history is available to copy.
