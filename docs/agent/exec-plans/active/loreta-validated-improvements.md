# LORETA validated improvements

Status: implementation complete; broad and CI verification in progress
Branch: `codex/loreta-validated-improvements`
Base: `codex/v3-release` at `503341ba`

## Scope

Implement the verified scientific-correctness and interaction improvements from
the October 2026 source-localization review. Keep the main page compact: replace
existing controls where needed, put model details in existing reports/dialogs,
and add no explanatory subtitles or unvalidated scientific claims.

The existing cortical-normal L2-MNE and vector-norm eLORETA calculations remain
independent and keep their inverse-method identities. This work does not change
sensor preprocessing, accepted harmonics, template anatomy, reference/noise
assumptions, or project.json. Individual MRI, independently recorded noise, and
new inferential contrast workflows require separate input/method validation;
this slice makes existing assumptions and numerical correctness inspectable.

## Work packages

1. Correct exhaustive sign-flip p-values, retain randomized-test correction,
   version statistical provenance, and test tails and minimum attainable p.
2. Replace inaccurate cluster/threshold wording in existing controls and method
   information; use concise factual labels rather than additional main-page text.
3. Make current/shared/fixed color limits consistent between previews and
   exports; use a documented sequential scientific palette.
4. Add MRI slice navigation and coordinate/orientation inspection using prepared
   values, keeping display interpolation distinct from original source samples.
5. Preserve worker progress and support cooperative source-build cancellation
   with safe publication behavior and no forced thread termination.
6. Extend existing validation reports with computable model/input quality facts;
   add reproducible statistical and source-recovery benchmarks with explicit
   synthetic scope, without claiming measured real-data localization accuracy.
7. Run focused LORETA, figure, GUI-static and broad precommit gates; record CI Qt
   coverage and a visible/manual smoke path, review, commit and push this branch.

## Scientific references

- Exact versus sampled p-values: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html
- Cluster-level interpretation: Sassenhagen & Draschkow (2019), https://doi.org/10.1111/psyp.13335
- Permutation assumptions: Winkler et al. (2014), https://pmc.ncbi.nlm.nih.gov/articles/PMC4010955/
- Scientific colour: Crameri et al. (2020), https://doi.org/10.1038/s41467-020-19160-7
- Template anatomy: https://mne.tools/1.9/auto_tutorials/forward/35_eeg_no_mri.html
- Covariance/rank: https://mne.tools/1.9/auto_tutorials/forward/90_compute_covariance.html
- Resolution: Hauk, Stenroos & Treder (2022), https://doi.org/10.1016/j.neuroimage.2022.119177

## Verification and progress

- Initial GUI, path, protected-boundary and source-localization audits passed.
- Root owns GUI/scale/progress integration, documentation and final review.
- Parallel owners cover inference, MRI slice interaction, and model reports.
- Local Qt execution is excluded by repository rules. No offscreen workflows.

- Implemented version 2 exact/sampled mask inference through one shared engine;
  corrected negative-tail selection and retained historical display fallback.
- Replaced Gaussian p-value display presets and individual-location significance
  wording with concise factual labels. Main controls gained no explanatory text.
- Replaced automatic checkbox/redundant label with current/shared/fixed scaling;
  comparison export refuses missing summaries. Viridis applies to all views.
- Corrected fsaverage affine-to-anatomical-plane mapping, added crosshairs and
  navigation in the slice image, and kept original-grid inspection in tooltips.
- MRI preview uses Agg-only worker rendering with coalescing/stale-result guards.
  Close waits for workers; source cancellation stops before publication.
- Existing reports now retain covariance/reference/input facts and versioned
  inference. Native cached-model recovery completed for both current methods;
  measured synthetic results and limitations are in `quality/loreta-validation.md`.
- Final focused verification: 432 LORETA tests, 656 GUI non-Qt tests, and 4
  figure-contract tests passed. Audits, Ruff, compilation, and strict MkDocs
  documentation build passed. Final review also locked image origin explicitly
  so custom Matplotlib settings cannot invert anatomical orientation labels.
- Broad precommit and remote CI checks are pending.
