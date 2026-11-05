# LORETA amplitude and descriptive comparisons

Status: implemented and source/Windows synthetic verification passed, 2026-11-04.
User authorized the amplitude metric and descriptive A/B/A−B comparison;
formal contrast inference is excluded. Qt CI/cross-platform acceptance remains.

## Scope and contracts

- Preserve existing signed-FIF inverses, Z values, numerical cache keys, locked
  preprocessing and canonical harmonic selections. No new inverse method.
- Add `source_metric: baseline_corrected_amplitude`: participant target spectral
  amplitude minus its neighboring-bin mean, signed and unclipped. Reuse cached
  participant arrays or fresh existing FIF derivatives. Keep Z as `z_score`;
  historical metadata may resolve to the existing Z identity, never amplitude.
- Amplitude units are method/window-dependent source spectral units, not scalp
  microvolts or calibrated current. Comparisons require identical source geometry,
  inverse/orientation, spectral settings and exact harmonics. Do not combine L2
  and eLORETA amplitudes or silently harmonize differing selections.
- Add amplitude payloads/participant diagnostics to existing transactional bundles.
  A producer-side comparison API prepares A, B and A−B on demand from retained
  participant data. GUI workers call it and adapt its prepared mappings; renderers
  never compute contrasts, group summaries or source estimates.
- Group comparisons retain independent cohorts for the same condition. Condition
  comparisons within one group use canonical complete participant pairs; A/B and
  A−B summaries all use those pairs. Mean/median/trimmed-mean differences summarize
  participant differences for paired conditions. Use common valid source support,
  retain full geometry and record counts, IDs, omissions, direction and settings.
- Comparisons operate before display thresholds or independent masks. Amplitude
  and contrast payloads carry no inherited inferential mask or p-values. Signed
  display intent is explicit `source_value_polarity: signed`; preserve missing
  support, show both signs, and use symmetric diverging color limits.
- Add a metric selector and Groups/Conditions comparison with A/B selectors.
  Show linked A/B panes or a full-size A−B view using a compact view selector;
  retain the camera across views. This keeps split hemispheres usable at 1280x900
  and avoids a third continuously allocated renderer. A/B share color limits;
  differences use their own symmetric range. Export labels identify metric,
  direction and cohort. MRI/export paths honor the same signed prepared values.
- Old bundles remain readable. Missing participant diagnostics/metric metadata
  produce a clear rebuild requirement, never invented amplitudes or unmatched
  contrasts. Request identity and bundle freshness protect asynchronous results.

## Ownership and checkpoints

| ID | State | Deliverable / next action |
| --- | --- | --- |
| A0 | Complete | Existing focused baseline: 728 passed; GUI/protected/path audits passed. Preserve unrelated marker-integrity/correlation-document changes. |
| A1 | Complete | Additive amplitude outputs, diagnostic sidecars, strict producer comparison API; numerical, pairing, signature/hash, publication and historical-Z regressions pass. |
| A2 | Complete | Signed cortical/volume/MRI values, diverging scale/palette and export parity; fixed limits preserve scientific-notation amplitudes. |
| A3 | Complete | Metric/group/condition/view selectors, canonical raw manifest IDs, stale-worker guards, cohort/omission labels and background snapshot exports. |
| A4 | Complete locally | Source/docs gates and Windows synthetic review passed, including signed MRI and export layout. Registered Qt/cross-platform acceptance remains below. |

## Resume and acceptance

Read this plan, tool rules and `git status`; continue only the unfinished acceptance.
Root owns docs, integration and final review; subagents own the isolated areas
above and reuse the root's task-specific keep-awake request (credentials stay out
of the repo). Do not touch unrelated work, private projects, standalone scripts,
fsaverage downloads or local offscreen Qt. Earlier user authorization permits a
visible Toolbox review with synthetic prepared data and cached anatomy.

Acceptance: known participant arrays produce exact signed amplitude/differences;
paired mismatches and missing cells are explicit; incompatible geometry/harmonics
fail; historical Z stays identical; negative and missing values survive all display
and export paths; stale async requests cannot restore a former metric/comparison.
Verify 1280x900 controls, A/B versus difference transitions, color/label parity,
signed MRI and PNG/PDF exports. Automated Qt remains CI coverage. No statistical
significance or improved localization-accuracy claim accompanies this feature.

## Acceptance evidence (2026-11-04)

- Focused LORETA: 845 passed; GUI: 774 passed; figures: 4 passed. Repo precommit:
  321 passed, 1 skipped; invariant audits, changed-file lint/compilation and strict
  MkDocs passed. These are source checks, not an installer or empirical study.
- Visible Windows review used the actual embedded page, cached fsaverage and
  synthetic participant arrays through the real augmentation/comparison API.
  Confirmed signed cortical and volume maps, shared A/B scaling, paired A/B
  n=3 from an original A n=4 with one explicit omission, and a one-renderer
  A−B view. MRI retained the contrast, palette and limits. Fixed limits retained
  ±2e−9. No inverse, real EEG/project data or anatomy download was run.
- Paired A/B surface and A−B MRI exports produced PDF/PNG pairs at 600 dpi.
  Both figures visually passed after measured cortical title wrapping/spacing;
  shared row geometry preserves equal brain scale. Relative doc links passed.
- Registered Qt smoke remains CI-only (`tests/gui/test_loreta_source_options_qt.py`).
  Cross-platform graphics and installer acceptance remain unclaimed. Do not
  resume private-project processing to satisfy this record.
