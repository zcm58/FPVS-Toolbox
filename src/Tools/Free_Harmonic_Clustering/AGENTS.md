# Free Harmonic Clustering Analysis Agent Contract

## Scope

This package owns the clean-room Free Harmonic Clustering Analysis backend and
its thin embedded beta GUI. Numerical preparation, inference, and export modules
remain GUI-neutral. The GUI gathers active-project context, prepares and reviews
one contrast, then delegates long work to signal-driven workers.

## Non-Negotiables

- The public tool title is `Free Harmonic Clustering Analysis`.
- Expose the GUI only through the Main App's Beta Tools route. Keep the page
  project-bound and discard its current-session state when the active project
  changes.
- Do not copy, translate, import, or redistribute the authors' restrictively
  licensed MATLAB code or `.mat` layout.
- Read scientific inputs only from original `FullFFT Amplitude (uV)` condition
  workbooks discovered through `Main_App.projects.load_project_dataset_index`.
  Do not read Stats-ready Summed BCA workbooks.
- Canonical groups and participant identities come only from `project.json`
  through the shared dataset index. Never infer group membership from folders.
- Keep the paper-faithful SNR/z/noise-window/L2 rules isolated from the locked
  Standard FPVS Screening method. Do not change or reuse its SNR/BCA selection
  results as substitutes.
- Free-harmonic adjacency is complete across retained harmonics at the same
  sensor. It is not a harmonic chain.
- New analyses use the fixed, versioned 197-edge FieldTrip-style BioSemi64
  graph reconstructed independently for the Toolbox. Record its edge list and
  hash, and do not describe it as the authors' adjacency matrix.
- Permute whole participant tensors. Never shuffle sensors, harmonics, or
  individual nodes independently.
- Positive and negative clusters use separate extreme-cluster nulls. Report
  cluster-level inference only; never label individual nodes pointwise
  significant.
- Require complete finite maps on one shared frequency grid and one shared
  BioSemi64 sensor set. Do not zero-fill or perform node-wise omission.
- Resolve all writes beneath the explicit managed project root. Do not mutate
  `project.json`, silently overwrite a prior run, or derive output paths from
  the current working directory.
- Treat the analysis as source-immutable. It may create an additive completed
  run bundle, but it must not change project settings, participant metadata,
  ledgers, QC decisions, or processed workbooks.
- Run exactly one ordered two-level contrast at a time. Version 1 has no
  omnibus/group-by-condition test, all-condition batch, result plots,
  historical-run browser, or clipboard/manuscript helper.
- Read base and oddball rates, conditions, canonical groups, exclusions,
  participants, and FullFFT availability dynamically. Do not add tool-local
  metadata overrides or hard-coded stimulation frequencies.
- Default to Hermann automatic harmonic selection. Fixed mode selects the
  highest oddball harmonic and fills through it; both modes dynamically exclude
  every base-rate overlap.
- Keep the Hermann-compatible profile fixed in version 1: 10,000 assignments,
  strict `z > 3.29`, +/-0.1-Hz selector/noise windows, participant/arm L2
  normalization, two-sided node-entry alpha `.01`, separate signed nulls, and
  raw sign-specific cluster alpha `.025`.

## Performance

- Build one deduplicated selected-column plan for all target/noise bins.
- Parse each selected FullFFT worksheet at most once per run.
- Convert workbook values immediately to contiguous NumPy arrays.
- Vectorize preparation and batched t-map generation across participants,
  sensors, and harmonics. Per-permutation cluster extraction may iterate.
- Do not run-scope cache every source DataFrame when each workbook is consumed
  once; that duplicates memory.
- Preserve timing and selected-column counts in provenance.

## Public API

Keep the package root small. Public callers should use:

- `prepare_project_contrast(...)`
- `run_free_harmonic_clustering(...)`
- `export_free_harmonic_run(...)`

Do not expose pandas frames, MNE objects, or XML-reader internals.

Embedded GUI callers use
`Tools.Free_Harmonic_Clustering.gui.FreeHarmonicClusteringPage`. Keep the
shared information content in `tool_info.py`; do not duplicate method text in
the page implementation.

## GUI And Outputs

- Use the shared `SectionCard`, `StatusBanner`, `ActionRow`, and tabbed
  `ToolInfoContent` patterns. Do not nest cards.
- The Setup & Preparation tab must freeze and display cohort, exclusions,
  harmonic selection, direction, and prepared array shape before enabling
  permutations.
- The Results tab shows the current session's latest run only, with significant
  clusters first by ascending raw tail p. Past runs remain available through
  Open Results Folder.
- The primary human-readable artifact is a polished
  `Free_Harmonic_Clustering_Results.xlsx` workbook. Retain machine-readable
  CSV, compressed-array, and manifest artifacts alongside it.
- Preparation and permutation work must run outside the UI thread. Workers
  communicate through signals and never touch widgets.

## Verification

Use synthetic/temp-project fixtures under `tests/free_harmonic_clustering/`.
Do not make tests depend on the developer's ACR project. Run:

```powershell
python .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
```

The headless numerical modules must not import PySide6. Keep GUI smoke coverage
registered for CI and do not run Qt locally on Windows.

The version 1 release gate is a visible end-to-end GUI reproduction of the
private ACR Neutral Happy comparison: 18 anxious versus 16 non-anxious
participants, retained H1/H2, positive H1 cluster at C1/Cz/CPz, and raw
sign-specific p approximately `.0043`. Do not bundle the ACR project or make
automated tests depend on it; automated preparation, inference, export, and GUI
coverage must use synthetic or temporary project fixtures.
