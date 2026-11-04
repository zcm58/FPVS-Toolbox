# LORETA validation and visible smoke

## Scientific scope

The current methods remain EEG-only fsaverage/BioSemi64 cortical-normal L2-MNE
and volume vector-norm eLORETA. Template geometry, ad-hoc covariance, locked
preprocessing and harmonic selection are unchanged. Model reports distinguish
recorded facts, missing provenance, numerical rank measured on signed averaged
derivatives, and model covariance rank. Rank does not establish covariance suitability.
No claim of empirical localization accuracy is made.

The November integrity repair marks every current source mask as exploratory.
Spectral-null centering/sign symmetry and population error control are not
qualified. Same-sample adaptive harmonics retain their selection qualification;
correction scope is one method/group/condition. Neither the synthetic checks below
nor a matching literature citation automatically promotes a project analysis.

## Native numerical reference and spectral diagnostic

`native_spectral_reference.py` builds a small analytic sphere with native MNE,
without downloads. Its independent signed-time inverse plus explicit sine/cosine
DFT produces frozen amplitude/window/Z references for normal L2 and vector
eLORETA, including odd/even FFT lengths and the Nyquist boundary. The tests compare
the production spectral route with these fixtures and retain dependency versions
and tolerances. Regeneration is an explicit reviewed action, never part of assertions.

The source-ready spectral diagnostic starts from simulated signed EEG, averages
repetitions, and uses the production native inverse/Hann/Z and cluster engine.
It tests white/correlated noise, unequal participant noise, fixed harmonics, a
separately labeled simplified same-sample selection stress, and injected signals.
It does not execute or qualify the locked Stats selector, earlier preprocessing,
real anatomy/electrode mismatch, or joint families across methods/conditions.

With `src` on `PYTHONPATH`, a full bounded run using already-installed fsaverage is:

```console
python -m Tools.LORETA_Visualizer.source_producers.source_spectral_diagnostics --model fsaverage --null-replicates 64 --signal-replicates 16 --participants 24 --permutations 999 --checkpoint .codex-tmp/loreta-spectral-checkpoint.json --max-seconds 2700 --output .codex-tmp/loreta-spectral-diagnostic.json
```

The checkpoint is atomic after each cohort. Add `--resume` with identical options
to continue after the time budget; source hashes/configuration/dependencies must
match. A partial run is not a completed receipt. Even zero rejections in 64 null
cohorts has a two-sided 95% binomial upper bound near 5.6%; this is diagnostic
evidence, not sufficient proof of nominal 5% error control. Expensive runs stay
outside routine pytest/CI.

### Completed 2026-11-04 experiment

[The spectral receipt](data/loreta-source-spectral-2026-11-04.json) records all
512 cohorts / 12,288 participant calculations, configuration, dependency versions
and numerical source hashes. Each cohort had 24 participants, four 20-second
repetitions at 200 Hz, four candidate harmonics and 999 sampled sign flips. It
used all 1,284 cortical and 1,821 volume sources; no support was missing.

| No-signal scenario | L2 cortical-normal | eLORETA vector-norm |
| --- | ---: | ---: |
| White noise | 0/64 | 0/64 |
| Correlated noise | 0/64 | 0/64 |
| Simplified same-sample selection stress | 0/64 | 1/64 |

Counts are cohorts with any retained cluster. Exact two-sided 95% binomial
intervals are 0–5.60% for 0/64 and 0.040–8.40% for 1/64, separately for each
scenario/method; do not pool them into a general error-control claim. The stress
selector is not the locked Stats selector.

Each injected-signal scenario retained a cluster in 16/16 cohorts (95% interval
79.41–100%). The chosen doses therefore do not locate a detection threshold.
Matched single-source spectral-Z peaks were approximately 52–60 mm from the L2
injection and 37–46 mm from the eLORETA injection. Different source geometries
and injection locations prevent a method ranking. These distances concern the
normalized spectral estimator, not the inverse-amplitude PSFs below. Detection
does not establish localization accuracy; inference qualification remains
exploratory after this experiment.

## November native resolution evidence

[The 2026-11-04 receipt](data/loreta-native-resolution-2026-11-04.json) extends the
inverse-only benchmark with sampled PSF/CTF spread and synthetic sensor noise/gain
perturbations. It retains model/source hashes and explicit scope. Eight sampled
L2-normal locations have PSF/CTF RMS spread 31.44–50.02 mm. Volume eLORETA's
orientation-block Frobenius summaries have PSF spread 44.14–55.14 mm and CTF
spread 38.84–63.46 mm; CTF peak distances range 10–70.71 mm. These different
orientation metrics do not rank the methods. Noise and gain perturbations are
not measured participant anatomy or electrode-location errors.

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

On 2026-11-04, the integrity repair passed 554 LORETA tests, 721 GUI static tests,
4 figure checks, and 1,208 project-I/O tests (14 skips). The repository handoff
gate passed 471 tests (1 skip), audits, Ruff and compilation. Strict MkDocs and
focused agent-doc links/owners pass. These gates overlap; their counts are not
independent totals. No local Qt/renderer or real-project run was performed.

## Rendering review (2026-11-04)

The subsequent [rendering improvement plan](../exec-plans/active/loreta-rendering-quality.md)
uses the user's explicit authorization for visible Windows review. The actual
Toolbox page, renderer and MRI worker were opened with cached fsaverage and
clearly labeled synthetic values; no private project or source calculation ran.
Native T1 anatomy, linked cursor navigation and compact/wide presentation were
reviewed separately from the scientific-integrity gates above.

| Local synthetic observation | Before | Updated |
| --- | ---: | ---: |
| Unsolicited render events during five seconds idle | 25 | 0 |
| Mean split rotation call, five 12° steps | 239 ms | 40–43 ms |
| Mean split color-range update, four changes | 236 ms | 67–77 ms |
| Anatomy voxel array | 128 MiB at resampled 0.5 mm | 16 MiB at native 1 mm |

The 655,360 split-hemisphere triangles were retained. Measurements are bounded
local call timings, not general GPU benchmarks or evidence of reduced total CPU
usage. Changes reuse actors/normals, stop idle redraws, apply guarded FXAA and
neutral matte lighting, and use a three-quarter volume camera. No SSAO, shadows,
ray tracing or additional anatomical smoothing was introduced.

MRI display prefers native full-head `T1.mgz` with `brain.mgz` fallback. Both
cached templates have the same tkregister frame. A volume-wide intensity window,
stable physical field of view and original-support Gaussian width keep planes
comparable. Missing sources stay transparent, including in Agg exports; the
averaged atlas retains its inherent softness. Native anatomy is cached across
coalesced preview requests; preview pixels are bounded independently of 600-dpi
publication output. See the plan for primary rendering references and rerun
conditions. Cross-platform graphics-driver and final-source Qt CI coverage remain
separate from this Windows visible review.

Rendering-change gates passed 588 LORETA tests, 721 GUI static tests, four figure
checks and 543 repository checks (one skip). The paired synthetic MRI export was
visually checked as PNG and rendered PDF at 600 dpi. Resizing rerenders after a
180 ms pause through the existing worker and preserves cursor/scale; identical
sizes and hidden/closing pages do no extra work.

CI-only coverage is registered in:

- `tests/gui/test_loreta_source_options_qt.py`
- `tests/gui/test_loreta_slice_viewer_qt.py`
- `tests/gui/test_loreta_preview_worker_qt.py`

The worker tests use bounded fake rendering and exercise latest-request
coalescing, stale results/errors, and deferred close. They are not a graphics-
driver or real-project usability test.

The Python package workflow runs these LORETA Qt files in a dedicated step before
the complete suite. The [published release source run](https://github.com/zcm58/FPVS-Toolbox/actions/runs/38789774709)
and [post-cleanup source run](https://github.com/zcm58/FPVS-Toolbox/actions/runs/39133936133)
passed historical LORETA Qt coverage. They do not verify the November integrity
changes; their updated Qt cases await CI. Neither source tests nor synthetic
diagnostics replace the human visible path below.

## Live two-group viewer

The [comparison plan](../exec-plans/active/loreta-group-comparison.md) records
the November 2026 implementation and acceptance. Exactly two explicit groups
share condition, exact summary, compatible numerical configuration and color
limits. Saved masks retain their separate within-group meaning. Missing or
ambiguous pairs fail without substituting data. No source or between-group
statistics are computed by this display.

Safe coverage lives in `tests/loreta/test_group_comparison.py`,
`test_group_comparison_gui.py`, `test_camera_link.py` and
`test_renderer_updates.py`; the existing registered source-options Qt smoke
adds comparison toggle/export/MRI eligibility checks. Native-camera tests check
VTK modification time as well as camera values, preventing a visually stale
peer after camera copying. The scoped Windows synthetic review verified initial
framing, linked drag/zoom/reset, split/combined/volume changes, condition and
summary updates, missing-pair failure, resize and MRI handoff. Real-project,
cross-platform graphics and final-source native Qt CI remain unclaimed.

Manual extension: with two canonical groups, enable **Compare groups**, check
both group/count/mask captions and one scale, rotate either pane, change display
controls, and disable/re-enable comparison. Verify incomplete pairs fail clearly;
MRI exits comparison. Close during loading and verify worker completion precedes
renderer cleanup. Repeat with one and three groups to verify unavailable reasons.

## Visible manual smoke path

Run only in an approved visible environment on Windows 11 or CachyOS:

1. Open LORETA with existing cortical and volume outputs in a 1280×900 workspace.
   Verify the main controls fit without page scrolling or explanatory subtitles.
2. Switch between conditions using current, all-conditions and fixed scales.
   Compare preview colorbar limits with single/stacked PNG/PDF exports. A condition
   without the chosen summary must not contribute a fallback summary.
3. Open volume MRI slices. Check axial/coronal/sagittal anatomy and L/R labels.
   Drag within each plane: its slice stays fixed while the other two update;
   crosshairs follow the pointer and settle at release. Drag outside the starting
   panel to check clamping, then resize/hide to check cancellation. Click, use
   arrows, scroll over each plane, and use Page Up/Down. Tooltips must
   show MRI RAS millimetres and original grid values, not interpolated pixels.
   Switch conditions to retain cursor planes; Home/Reset restores shared planes.
4. Change conditions rapidly during preview rendering; obsolete display contexts
   must never appear. Same-context intermediate drag frames are allowed without
   moving the pointer backward. Export is disabled while a preview renders. Check that MRI
   figure labels/colorbar remain inside both matching 600-dpi PNG/PDF files.
5. Rebuild source maps and observe real stage messages. Use Options → Cancel
   rebuild. An existing published method must remain intact if cancelled before
   publication; completed sibling methods stay usable. Close during a build or
   preview and verify the page waits for worker completion without freezing.
   Change accepted harmonics or participant group/QC eligibility; old results
   must not load as current. A failed sibling must not reappear after partial
   success. Historical explicit import must show unverified current provenance.
6. Rebuild an exact small-cohort fixture and inspect version 2 estimator/count/
   minimum-p metadata and report covariance/input provenance. Load historical
   output separately and verify its saved mask remains unchanged.
7. Use a synthetic prepared payload with declared missing sources. Inspect both
   mask states, cortical painting, volume contours, MRI slices and exports:
   missing locations must stay blank and cannot alter the color scale. A missing
   hemisphere ROI must have unavailable comparisons. Confirm report validity,
   rank and exploratory-inference disclosures match the prepared metadata.

## References

- [SciPy permutation tests](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html): exact and sampled estimators.
- [Sassenhagen & Draschkow (2019)](https://doi.org/10.1111/psyp.13335): cluster-level interpretation.
- [Winkler et al. (2014)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4010955/): permutation assumptions.
- [Hauk, Stenroos & Treder (2022)](https://doi.org/10.1016/j.neuroimage.2022.119177): multiple resolution metrics.
- [MNE template MRI](https://mne.tools/1.9/auto_tutorials/forward/35_eeg_no_mri.html) and [covariance](https://mne.tools/1.9/auto_tutorials/forward/90_compute_covariance.html): model assumptions.
- [Crameri et al. (2020)](https://doi.org/10.1038/s41467-020-19160-7): scientific colour communication.
