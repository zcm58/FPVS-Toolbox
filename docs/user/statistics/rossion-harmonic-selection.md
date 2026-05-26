# Harmonic selection for Summed BCA

Use this page when you need to understand or report which oddball
harmonics contributed to the Stats tool's Summed BCA dependent variable.

## Current options

The default and primary policy is **Group-level significant harmonics
(Volfart/Retter/Rossion style)**. This option selects one common harmonic
list at the group level, then applies that same list to every participant,
selected condition, and ROI.

The alternate policy is **Fixed / predefined harmonic list**. By default it
uses 1.2, 2.4, 3.6, 4.8, and 7.2 Hz. Base-rate overlaps such as 6, 12, and
18 Hz are excluded by default. The same fixed list is applied to every
participant, selected condition, and ROI. The source `BCA (uV)` sheets must
contain those exact harmonic columns.

## Group-level significant harmonics

This default policy follows the common FPVS idea that the oddball
response can appear at the oddball frequency and its harmonics. For a
6 Hz base rate with every fifth image as the oddball, candidate oddball
harmonics are 1.2, 2.4, 3.6, 4.8, 6.0, 7.2 Hz, and so on. Harmonics that
overlap the base rate, such as 6, 12, and 18 Hz, are excluded from the
oddball sum.

The oddball frequency is locked at 1.2 Hz. The BCA harmonic upper limit
only sets where the 1.2 Hz harmonic list stops. For example, an upper
limit of 30 Hz tests 1.2, 2.4, 3.6, ... through 30.0 Hz; it does not
change the oddball frequency to 30 Hz, 6 Hz, or any other spacing.

Selection is performed from the `FullFFT Amplitude (uV)` sheets:

1. The tool builds a grand-averaged raw amplitude spectrum across the
   final included participants and selected conditions. Within each workbook,
   the FullFFT amplitudes are averaged across scalp electrodes before entering
   the group average.
2. Z-scores are computed at candidate oddball harmonics from that
   grand-averaged amplitude spectrum using neighboring-bin noise.
3. Non-base oddball harmonics above the group-level z threshold are
   selected.
4. Participant-level Summed BCA is computed from the `BCA (uV)` sheets
   using the selected common harmonic list.

The neighboring-bin noise calculation is fixed for this policy. For each
candidate harmonic, the tool uses the 10 FFT bins below and 10 FFT bins above
the target, excludes the immediately adjacent bins and the target bin itself,
then removes the single lowest and single highest finite amplitude values from
the remaining noise bins. The noise mean and population standard deviation are
computed from the remaining values, and the candidate harmonic is selected only
when `(target amplitude - noise mean) / noise SD` is greater than 1.64.

The policy requires exact nominal oddball-harmonic columns in the
`FullFFT Amplitude (uV)` sheet, such as `1.2000_Hz`, `2.4000_Hz`,
and `3.6000_Hz`. If the FullFFT frequency grid is off-bin, the tool
stops before reading amplitude rows or aggregating BCA values so the
workbooks can be regenerated with locked FFT crop output.

The selected participant-level `BCA (uV)` columns must also match exactly.
The group-level policy does not use nearest frequency columns or silent
fallback harmonics.

The output remains Summed BCA in microvolts. SNR is not used as the
dependent variable for the Stats models.

## Reporting

For fixed/predefined harmonic lists, report the selected frequencies and
whether base-rate overlaps were excluded.

For group-level significant harmonics, report that harmonics were
selected from the grand-averaged `FullFFT Amplitude (uV)` spectrum,
state the z threshold, list the selected harmonics, list excluded
base-rate overlaps, and note that the same harmonic list was applied to
all participants, selected conditions, and ROIs.

The Stats-ready workbook includes a `Harmonic_Selection` sheet with the
selected harmonics, z-scores, base-overlap exclusions, selection scope,
matched FullFFT columns, grand-average candidate amplitudes, and local
noise bins used for the group-level z-score calculation.
