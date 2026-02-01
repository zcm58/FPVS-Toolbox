# Individual-level Detectability

## Technical documentation

### Purpose and scope
The individual-level detectability tool generates per-condition, participant-level detectability figures from **existing FPVS Toolbox Excel exports**. It **does not recompute** FFT/BCA/SNR/Z metrics; it only reads the exported sheets and produces figures. Each participant panel contains (i) a scalp topomap of Stouffer-combined Z scores across oddball harmonics and (ii) a centered SNR mini-spectrum panel around each harmonic, averaged across significant electrodes and then across harmonics.【F:src/fpvs_individual_detectability.py†L1-L20】

### Required inputs (Excel format)
The script expects a workbook per participant with the following sheets and columns:

- **Sheet `Z Score`**
  - Electrode column: `Electrode`.
  - Harmonic columns named like `1.2000_Hz` (any numeric frequency with `_Hz` suffix). Only the frequencies in `ODDBALL_HARMONICS_HZ` are required. Missing harmonic columns raise a hard error.【F:src/fpvs_individual_detectability.py†L72-L105】【F:src/fpvs_individual_detectability.py†L270-L311】
- **Sheet `FullSNR`**
  - Electrode column: `Electrode`.
  - Frequency columns named `*_Hz` covering bins within ±`HALF_WINDOW_HZ` around each oddball harmonic. The script filters columns by frequency to keep only the bins needed for the mini-spectrum window.【F:src/fpvs_individual_detectability.py†L96-L101】【F:src/fpvs_individual_detectability.py†L250-L279】

The oddball harmonic list is fixed (`ODDBALL_HARMONICS_HZ = [1.2, 2.4, 3.6, 4.8, 7.2]`), and the script **fails fast** if the base frequency (`SKIP_BASE_FREQ_HZ = 6.0`) appears in the list.【F:src/fpvs_individual_detectability.py†L77-L83】【F:src/fpvs_individual_detectability.py†L986-L994】

### Z-score combination across harmonics (Stouffer)
For each electrode, the script combines Z scores across the oddball harmonics via Stouffer’s method:

- Let **k** be the number of oddball harmonics.
- For each electrode, collect Z values `z_i` at each harmonic.
- Compute:

```
Z_comb = (sum_{i=1..k} z_i) / sqrt(k)
```

Significance thresholding is one-tailed and positive direction only:

- Significant if `Z_comb >= Z_THRESHOLD` (default `1.64`).【F:src/fpvs_individual_detectability.py†L82-L87】【F:src/fpvs_individual_detectability.py†L292-L327】

### FDR correction (Benjamini–Hochberg)
If `USE_BH_FDR` is enabled (default `True`), the script applies BH-FDR correction to the combined Z values:

- Convert combined Z to one-tailed p-values: `p = 1 − Φ(Z_comb)`.
- Apply BH-FDR at `alpha = FDR_ALPHA` (default `0.05`).
- **Scope:** across electrodes **within a participant file** (per participant, per condition).
- Final significance mask is the **intersection** of the Z threshold and BH reject decisions: `(Z_comb >= Z_THRESHOLD) AND (BH reject)`.【F:src/fpvs_individual_detectability.py†L82-L87】【F:src/fpvs_individual_detectability.py†L312-L327】

Dependency behavior:

- Uses `statsmodels.stats.multitest.multipletests(method="fdr_bh")` when available.
- Falls back to the internal `_bh_fdr_reject` implementation otherwise.【F:src/fpvs_individual_detectability.py†L55-L70】【F:src/fpvs_individual_detectability.py†L193-L223】【F:src/fpvs_individual_detectability.py†L312-L327】

### Topomap plotting behavior (critical stability note)
!!! warning "Do not use NaN masking"
    Non-significant electrodes are **set to exactly `Z_THRESHOLD`** and rendered with a colormap whose minimum is white. This avoids `NaN` values, which can cause **blank or all-white heads** due to MNE interpolation failures. The data passed to `mne.viz.plot_topomap()` is always finite for stability.【F:src/fpvs_individual_detectability.py†L24-L41】【F:src/fpvs_individual_detectability.py†L327-L392】【F:src/fpvs_individual_detectability.py†L642-L671】

Montage behavior:

- Uses `MONTAGE_NAME = "biosemi64"`.
- Electrode names are normalized before matching.
- In `DEBUG` mode, **any mapping failure raises an error** to surface label issues early.【F:src/fpvs_individual_detectability.py†L102-L107】【F:src/fpvs_individual_detectability.py†L330-L389】

### SNR mini-spectrum computation
For each participant:

1. Determine significant electrodes from the combined Z significance mask.
2. Pull the `FullSNR` values for those electrodes.
3. For each harmonic `f`:
   - Extract bins in `[f − HALF_WINDOW_HZ, f + HALF_WINDOW_HZ]`.
   - Convert to relative frequency `x = (bin − f)`.
   - Average across significant electrodes at each bin.
4. Align relative-frequency bins across harmonics (rounded to 4 decimals) and average across harmonics to produce a single centered SNR curve.【F:src/fpvs_individual_detectability.py†L392-L467】

Display rules:

- Fixed x-limits: ±`HALF_WINDOW_HZ`.
- Fixed y-limits: `[SNR_YMIN_FIXED, SNR_YMAX_FIXED]` (defaults `0` to `2`).
- Reference lines: vertical at `0 Hz`, horizontal at `SNR = 1`.
- If `n_sig <= 0` (or the curve is missing), the SNR panel is hidden entirely.【F:src/fpvs_individual_detectability.py†L88-L95】【F:src/fpvs_individual_detectability.py†L650-L717】

### Figure layout + export
Layout defaults to **letter-size portrait** output for manuscript use:

- `USE_LETTER_PORTRAIT = True` produces an 8.5×11 in figure with reserved title and colorbar bands.
- Grid bounds are computed from `PAGE_MARGIN_IN`, `TITLE_BAND_IN`, and `COLORBAR_BAND_IN`.
- A centered horizontal colorbar is placed in the reserved band.【F:src/fpvs_individual_detectability.py†L112-L141】【F:src/fpvs_individual_detectability.py†L624-L768】

Export behavior:

- `FIG_DPI = 600`, format PNG.
- In letter mode, the figure is saved **without** `bbox_inches="tight"` to preserve physical size.
- Figure title uses **Times New Roman**; a blank title omits the suptitle entirely.
- Output filename stems are sanitized for Windows compatibility via the PySide6 naming dialog.【F:src/fpvs_individual_detectability.py†L131-L140】【F:src/fpvs_individual_detectability.py†L719-L768】【F:src/fpvs_individual_detectability.py†L772-L875】

### Reproducibility + recommended reporting
When reporting results generated with this tool, include:

- Harmonics list: `ODDBALL_HARMONICS_HZ` and exclusion of `SKIP_BASE_FREQ_HZ` (6 Hz).
- Stouffer combination formula for `Z_comb` and one-tailed threshold (`Z_THRESHOLD = 1.64`).
- BH-FDR settings (`USE_BH_FDR = True`, `FDR_ALPHA = 0.05`) and per-participant electrode scope.
- SNR window (`HALF_WINDOW_HZ = 0.2 Hz`), fixed SNR y-axis (`0–2`), and reference lines.
- Montage (`biosemi64`) and finite-vector topomap rendering strategy (non-sig set to threshold).【F:src/fpvs_individual_detectability.py†L77-L141】【F:src/fpvs_individual_detectability.py†L292-L392】【F:src/fpvs_individual_detectability.py†L392-L717】

### Relation to prior figure styles
A similar figure style appears in David et al. (2025), and the per-participant grid layout with topomap plus centered SNR mini-spectrum is aligned with that style for visual comparability in individual-level reporting.【F:src/fpvs_individual_detectability.py†L1-L20】

David, J., Quenon, L., Hanseeuw, B., Ivanoiu, A., Volfart, A., Koessler, L., & Rossion, B. (2025). **An objective and sensitive electrophysiological marker of word semantic categorization impairment in Alzheimer's disease.** *Clinical Neurophysiology*, 170, 98–109. https://doi.org/10.1016/j.clinph.2024.12.018.【F:docs/relevant-publications.md†L21-L28】

## Manuscript / thesis-ready text (copy/paste)

The individual-level detectability tool generates participant-level detectability figures using only the FPVS Toolbox Excel exports (no recomputation of FFT/BCA/SNR/Z). For each participant and condition, Z scores at the oddball harmonics are combined with Stouffer’s method (Z_comb = sum(z_i)/√k), thresholded one-tailed in the positive direction (Z_comb ≥ 1.64), and optionally further filtered via Benjamini–Hochberg FDR across electrodes within each participant file (α = 0.05). The resulting topomap is rendered with a finite vector: non-significant electrodes are set to the threshold value so that the colormap’s floor renders as white, avoiding NaN interpolation failures in MNE topomap plotting. A centered SNR mini-spectrum is computed by averaging FullSNR bins within ±0.2 Hz of each oddball harmonic across significant electrodes, aligning relative-frequency bins across harmonics, and averaging across harmonics, with fixed axes and reference lines for interpretability. The figure is exported as a 600 DPI PNG for individual-level detectability reporting.【F:src/fpvs_individual_detectability.py†L1-L20】【F:src/fpvs_individual_detectability.py†L77-L141】【F:src/fpvs_individual_detectability.py†L292-L717】

Text and figure-generation approach may be reused with attribution; cite the FPVS Toolbox using the project’s preferred citation (Murphy Z., et al., FPVS Toolbox: Automated preprocessing and statistical analysis for fast periodic visual stimulation EEG experiments; manuscript in preparation).【F:docs/relevant-publications.md†L52-L57】
