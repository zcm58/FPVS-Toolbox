# Free Harmonic Clustering Analysis Agent Contract

## Scope

This package owns the GUI-neutral, clean-room Free Harmonic Clustering Analysis
backend. It reads managed post-processing workbooks, preserves sensor x harmonic
structure, and performs one declared two-level cluster-permutation contrast per
run.

## Non-Negotiables

- The public tool title is `Free Harmonic Clustering Analysis`.
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

## Verification

Use synthetic/temp-project fixtures under `tests/free_harmonic_clustering/`.
Do not make tests depend on the developer's ACR project. Run:

```powershell
python .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
```

The headless package must not import PySide6 and requires no local Qt tests.

