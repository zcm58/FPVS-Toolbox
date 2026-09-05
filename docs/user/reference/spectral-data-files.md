# Spectral Data Files

New processing results save two files together: the usual condition workbook
and an uncompressed NumPy companion ending in `.spectra.<hash>.npz`.
The companion stores the complete FullFFT amplitudes and the already-calculated
FullSNR curves. Excel keeps the smaller FFT, BCA, SNR, Z-score and QC reports.
The `FullFFT Amplitude (uV)` and `FullSNR` tabs name the companion file.

All original FFT bins and float64 values are retained. This removes Excel's
column limit: a 120-second condition sampled at 512 Hz has 30,721 FFT bins,
which the companion can store without truncation. The change does not alter
trigger timing, EEG processing, averaging, local noise windows or statistics.

The Toolbox's plots, maps, Stats, Free Harmonic Clustering and Individual
Detectability read the appropriate files automatically. Existing Excel-only
projects remain readable. They are not converted automatically; new processing
exports use the companion format.

**Keep each workbook and its companion together when moving, backing up or
sharing results.** Preserve their filenames. The workbook names its companion
using a relative filename and verifies its contents. Restore a missing file
from backup or reprocess the affected recording; refreshing downstream results
alone cannot recreate missing spectral arrays.

For scripts running in the Toolbox Python environment, the shared reader works
with both formats:

```python
from Main_App.io.spectral_data import read_spectral_sheet

# workbook_path points to the participant-condition Results.xlsx file.
fft = read_spectral_sheet(workbook_path, sheet_name="FullFFT Amplitude (uV)")
snr = read_spectral_sheet(workbook_path, sheet_name="FullSNR")
electrodes = fft["Electrode"].to_numpy()
amplitudes_uv = fft.iloc[:, 1:].to_numpy()
```

New FullFFT frames also expose exact frequencies in
`fft.attrs["spectral_metadata"]["frequencies_hz"]`. The column labels retain the
familiar four-decimal display format. The SNR curve has its own established
0.01-Hz display grid; do not assign the FullFFT grid to that curve.

Outside the Toolbox, the companion can be opened with
`numpy.load(companion_path, allow_pickle=False)`. `metadata_json` declares the
ordered sheet names; each sheet index has `sheet0_columns`, `sheet0_electrodes`
and `sheet0_values` (and the corresponding `sheet1_*` arrays for FullSNR).
`fullfft_frequencies_hz` holds the exact FFT grid. The Toolbox reader also
checks the workbook's checksum declaration, which a direct NumPy load does
not do.
