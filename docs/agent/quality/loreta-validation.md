# LORETA validation and visible smoke

## Scientific scope

The current methods remain EEG-only fsaverage/BioSemi64 cortical-normal L2-MNE
and volume vector-norm eLORETA. Template geometry, ad-hoc covariance, locked
preprocessing and harmonic selection are unchanged. Model reports distinguish
recorded facts, missing provenance, and participant rank that was not measured.
No claim of empirical localization accuracy is made.

Version 2 cluster inference uses exact tail proportions when every sign pattern
is enumerated and plus-one correction for random sampling. SciPy parity tests
cover positive, negative and two-sided single-source cases. A complete synthetic
64-pattern sign orbit with connected/disconnected sources gives 3/64 positive-
tail and 2/64 two-sided familywise rejections at alpha .05. This checks the
conditional sign-symmetric source-map fixture, not the complete EEG/spectral
pipeline or data-adaptive harmonic selection.

## Reproducible native inverse diagnostic

From the repo environment, with `src` on `PYTHONPATH`:

```console
python -m Tools.LORETA_Visualizer.source_producers.source_recovery_benchmark --output <diagnostic-output.json> --probe-count 8
```

This opt-in command uses installed template files without fetching them. It
injects isolated 1 nAm sources through each native forward model and applies that
model's current inverse/orientation reduction. Probe locations are evenly spaced
source indices, not a representative anatomical sample. It reports all peak ties,
energy-weighted RMS distance from the injected source, and energy outside 20 mm.

Measured on 2026-10-15 with MNE 1.9.0 and NumPy 2.3.1:

| Method | Sources | Probes | Nearest peak distance (mm) | RMS spread (mm) |
| --- | ---: | ---: | ---: | ---: |
| Cortical-normal L2-MNE | 1,284 | 8 normal | 0–40.29 | 31.44–50.02 |
| Volume vector-norm eLORETA | 1,821 | 24 (8 locations × 3 axes) | 0 | 41.23–58.27 |

These are noiseless, isolated, same-model, inverse-only results. They do not test
head-model mismatch, correlated sources, noise, preprocessing, spectral z scores,
or statistical calibration, and do not rank the methods. In particular, zero peak
error for the selected probes does not imply zero spread or accurate localization
in a participant.

## Verification

Use the repo environment with the verification driver. Local execution excludes
Qt tests:

```console
python .agents/scripts/verify.py --scope loreta --tier focused
python .agents/scripts/verify.py --scope figures --tier focused
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

On 2026-10-15, the final focused run passed 432 LORETA tests; GUI and figure gates
passed 656 and 4 tests respectively. The broad local run passed 7,417 tests with
25 skips. Seven additional regressions added after broad collection are covered
by the final focused run. Audits, Ruff, compilation and strict MkDocs build pass.

CI-only coverage is registered in:

- `tests/gui/test_loreta_source_options_qt.py`
- `tests/gui/test_loreta_slice_viewer_qt.py`
- `tests/gui/test_loreta_preview_worker_qt.py`

The worker tests use bounded fake rendering and exercise latest-request
coalescing, stale results/errors, and deferred close. They are not a graphics-
driver or real-project usability test.

## Visible manual smoke path

Run only in an approved visible environment on Windows 11 or CachyOS:

1. Open LORETA with existing cortical and volume outputs in a 1280×900 workspace.
   Verify the main controls fit without page scrolling or explanatory subtitles.
2. Switch between conditions using current, all-conditions and fixed scales.
   Compare preview colorbar limits with single/stacked PNG/PDF exports. A condition
   without the chosen summary must not contribute a fallback summary.
3. Open volume MRI slices. Check axial/coronal/sagittal anatomy and L/R labels.
   Click, use arrows, scroll over each plane, and use Page Up/Down. Tooltips must
   show MRI RAS millimetres and original grid values, not interpolated pixels.
   Switch conditions to retain cursor planes; Home/Reset restores shared planes.
4. Change conditions rapidly during preview rendering; only the newest image or
   error may appear. Export is disabled while a preview renders. Check that MRI
   figure labels/colorbar remain inside both matching 600-dpi PNG/PDF files.
5. Rebuild source maps and observe real stage messages. Use Options → Cancel
   rebuild. An existing published method must remain intact if cancelled before
   publication; completed sibling methods stay usable. Close during a build or
   preview and verify the page waits for worker completion without freezing.
6. Rebuild an exact small-cohort fixture and inspect version 2 estimator/count/
   minimum-p metadata and report covariance/input provenance. Load historical
   output separately and verify its saved mask remains unchanged.

## References

- [SciPy permutation tests](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html): exact and sampled estimators.
- [Sassenhagen & Draschkow (2019)](https://doi.org/10.1111/psyp.13335): cluster-level interpretation.
- [Winkler et al. (2014)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4010955/): permutation assumptions.
- [Hauk, Stenroos & Treder (2022)](https://doi.org/10.1016/j.neuroimage.2022.119177): multiple resolution metrics.
- [MNE template MRI](https://mne.tools/1.9/auto_tutorials/forward/35_eeg_no_mri.html) and [covariance](https://mne.tools/1.9/auto_tutorials/forward/90_compute_covariance.html): model assumptions.
- [Crameri et al. (2020)](https://doi.org/10.1038/s41467-020-19160-7): scientific colour communication.
