# LORETA Volume Rendering

Status: complete; ready for plan retirement
Owner: FPVS Toolbox
Feature branch: `codex/loreta-volume-rendering`

## Goal

Keep the Hauk-informed L2-MNE workflow strictly cortical while correcting the
independent eLORETA volume display so every retained volume-grid location can
be rendered in 3D without cerebral-pial clipping or screen-aligned point
sprites.

## Locked Decisions

- Source estimation, participant arrays, cluster adjacency, saved masks,
  payload schemas, and project outputs do not change.
- L2-MNE remains a cortical-surface source model and keeps split-hemisphere and
  combined-cortical displays only.
- eLORETA remains the EEG-only fsaverage 10 mm volume-grid Toolbox extension.
- The cerebral pial meshes are not a validity or clipping boundary for volume
  sources and must not alter volume color-scale inputs.
- A skull-stripped fsaverage whole-brain shell is the preferred interactive 3D
  anatomical context when available. It is display anatomy, not source-space
  support and must not silently remove source points.
- MRI slices remain the preferred view for anatomical localization. The 3D
  contour is display interpolation around tested source-grid locations, not an
  anatomical structure or additional inferential extent.
- Empty volume payloads render no activation. One- and two-location payloads
  render deterministic isotropic 3D contours tied to volume-grid spacing,
  never fixed-size screen glyphs.

## Implementation

1. Remove pial enclosure filtering from GUI scalar-range preparation and from
   renderer point/grid handling.
2. Extend display-only volume smoothing to support one or more retained points
   with a source-spacing hint and closed contours.
3. Build and cache an optional whole-brain context mesh from fsaverage
   `brainmask.mgz`, transformed by the same surface-RAS display transform as
   the cortical mesh.
4. Use that context for volume 3D payloads while leaving cortical paint,
   split-hemisphere rendering, and projection geometry unchanged.
5. Separate method/display labels and explain the surface-versus-volume
   interpretation in tool and user documentation.
6. Add non-Qt regressions for sparse contours, full volume-point retention,
   auto-scale retention, anatomy-context caching, and unchanged cortical
   routing. Update CI-only Qt smoke definitions only where widget behavior
   changes.

## Verification

- `python .agents/scripts/verify.py --scope loreta --tier focused`
- `python .agents/scripts/verify.py --scope gui --tier focused`
- GUI import and protected/source-localization audits from their repo skills.
- Repository precommit gate after focused checks pass.
- Visible/manual smoke: compare L2 split/combined surface displays, eLORETA 3D
  whole-brain context, sparse significant masks, MRI slices, mask toggle,
  color scale, opacity, orbit/reset, and figure export without offscreen Qt.

## Progress

- 2026-08-15: Created the feature branch from `main`; the focused LORETA
  baseline passed with 275 tests. GUI and protected/source-localization audits
  passed. The current square was traced to pial clipping followed by a sparse
  point-sprite fallback.
- 2026-08-15: Updated the tool contract and user-method documentation to keep
  Hauk-style L2-MNE cortical, identify eLORETA as the independent Toolbox
  volume extension, prohibit pial/anatomical clipping of prepared volume
  estimates, describe 3D interpolation as display-only, and prefer MRI slices
  for anatomical localization.
- 2026-08-15: Implemented full-support volume interpolation, sparse 3D
  contours, source-spacing-sized sphere fallback, and an optional cached
  `brainmask.mgz` whole-brain context. Added method-compatible display choices,
  truthful mask/interpolation copy, non-Qt regressions, and registered CI-only
  Qt selector coverage. The focused LORETA gate passed 289 tests; the full
  precommit gate passed 1,529 tests with 3 skips. A real fsaverage cache probe
  loaded the 120,000-triangle pial display plus an 80,000-triangle whole-brain
  context. Local offscreen/pytest-qt execution remained intentionally skipped;
  the visible smoke path above remains the final interactive check.
- 2026-08-15: Merged the feature branch into
  `codex/harmonic-selection-strategies-plan` (`83f543d2`). A normal visible
  Windows 11 review exercised the corrected L2 split rendering, and the user
  confirmed that the exercised LORETA behavior works well. At the user's
  explicit direction, no further visible smoke is required. This closes the
  interactive acceptance requirement without claiming that every item in the
  longer optional comparison path was individually exercised.
