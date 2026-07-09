# Scalp Maps

Scalp Maps exports grand-average sensor-space topographies from processed FPVS
workbooks. It supports baseline-corrected amplitude (BCA), signal-to-noise ratio
(SNR), and summed-harmonic z-score maps.

## When To Use It

Use Scalp Maps after the selected conditions have been processed and the
project's ROI and frequency settings are final. The tool reads the active
project's Excel results by default and writes to `4 - Scalp Maps` under the
project results folder unless you choose another location.

## Inputs

Select one or more processed conditions, the metrics to draw, and the output
folder. Scalp Maps uses the same locked group-level significant-harmonic policy
as Statistical Analysis; it does not choose a separate set of harmonics for
each participant, condition, ROI, or metric.

The source workbooks must contain exact `"{frequency:.4f}_Hz"` columns in the
relevant sheets:

- `BCA (uV)` for BCA maps;
- `SNR` for SNR maps; and
- `Z Score` for z-score maps.

Workbooks missing exact selected columns are reported rather than matched to a
nearby frequency.

## How Values Are Combined

- BCA values are summed across the selected harmonics for each participant and
  electrode, then averaged across participants.
- SNR values are averaged across the selected harmonics for each participant
  and electrode, then averaged across participants.
- Z-scores are combined as `sum(z) / sqrt(K)`, where `K` is the number of
  selected harmonics, then averaged across participants.

Frequency-domain participant and electrode exclusions recorded by the project
are applied before aggregation.

## Figure Options

You can export individual condition maps or a paired condition figure. In paired
mode, selected metrics are arranged as rows with the two conditions as columns,
and the conditions share a color scale for each metric.

BCA and SNR can use fixed or automatic color limits. The initial fixed ranges
are 0.0–0.4 µV for BCA and 1.0–1.5 for SNR. Z-score maps use a configurable
lower display threshold of 1.64 by default; values below the display threshold
are white.

Rendered BCA maps clip negative values to the low end of the color scale, but
the signed values remain in the source-data workbook.

## Outputs

The tool writes matching 600-DPI `.png` and `.pdf` figures and
`Publication_Scalp_Maps_Source_Data.xlsx`. The source workbook contains long-form
participant values, grand-average plotted values, selection parameters, and
diagnostics. Keep it with the figures so the plotted values and harmonic policy
remain auditable.

Scalp topographies interpolate measurements across electrodes. They show the
sensor-space distribution and should not be described as anatomical source
locations.

## References

- Hauk, O., et al. (2021). [Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*, 118460.
- Volfart, A., et al. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- [Scalp Maps implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Publication_Maps).
