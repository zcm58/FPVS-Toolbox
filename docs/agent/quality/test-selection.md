# Test Selection

Use the repository verification driver as the executable source of truth. It
selects `.venv1` or `.venv`, keeps output compact, applies the explicit Qt-test
registry, and composes the tests, audits, compilation, and lint checks required
for each scope.

```powershell
python .agents/scripts/verify.py --scope <scope> --tier focused
```

Run `python .agents/scripts/verify.py --scope repo --tier precommit` for the
broad local handoff gate. Do not duplicate its pytest lists in documentation;
update the driver when executable coverage changes.

## Qt Execution Boundary

PySide6/pytest-qt tests are CI-only by default. Do not run them on local Windows
machines, do not set `QT_QPA_PLATFORM=offscreen`, and do not launch ad-hoc
offscreen Qt scripts. They can freeze indefinitely even when a filename or
marker does not obviously identify it as a Qt test.

For GUI changes, keep the CI Qt coverage definition current, run the local
focused scope for non-GUI checks, and document a visible/manual smoke path. Run
Qt tests locally only when the user explicitly approves a safe visible GUI
environment.

## Scope Map

| Scope | Local focused coverage | Qt coverage retained for CI |
| --- | --- | --- |
| `gui` | GUI import boundaries, syntax/static checks, non-window contracts | Main-window layout/wiring, dialogs, settings/status, embedded-page smoke |
| `updates` | Release selection, download/install backend, packaging syntax, GUI-module compilation | Update dialog and manager interaction |
| `project-io` | Project settings, enumeration/scanning, result paths, manifest contracts | File dialogs and visible project workflows |
| `processing` | Order/fingerprint, QC calibration, persistence, FFT crop, runner/export contracts | Processing-window wiring and Qt workers |
| `plot-generator` | Excel/config helpers, aggregation, FFT/SNR behavior, rendering and export contracts | Plot Generator page/layout/workflow smoke |
| `publication-maps` | Source workbook, processing-time harmonics, BCA/SNR rendering, paired outputs, colorbars | Embedded Scalp Maps page behavior |
| `ratio-calculator` | Ratio calculations, ROI behavior, plots and exports | Ratio Calculator page/workflow smoke |
| `sequence-figure` | Renderer behavior and high-DPI outputs | Embedded Sequence Figure wiring |
| `sensitivity-analysis` | Paired-test/RM-ANOVA power math plus mixed-model simulation, search, cancellation, uncertainty, and validation | Embedded page wiring, background worker, controls, results, reset, information tabs, and clipping smoke |
| `stats` | Data/project context, pipeline, DV/harmonic rules, FullSNR, exports and reporting | Stats layout, focus, and window workflow smoke |
| `loreta` | Payloads, source producers, project exports, rendering helpers and legacy boundaries | Embedded visualizer interaction and Qt worker smoke |
| `figures` | Shared figure-style contract and focused output/rendering checks | Figure-export dialog interaction where applicable |
| `legacy-boundary` | Retired package/source-localization audits and focused compatibility checks | None by default |
| `repo` with `precommit` | Broad non-Qt handoff gate: audits, changed-file static checks, and safe tests | CI runs the separate Qt job |

## Selection Rules

- Start with the scope that owns the changed behavior. Add a second scope only
  when the change crosses a documented boundary.
- The file and directory names under `tests/` are orientation aids, not proof
  that a test is locally safe. The driver's Qt registry decides execution.
- Add focused tests next to the owning workflow. Register new Qt-dependent
  tests before relying on local scope output.
- Use isolated temporary paths for file/project tests; never depend on a
  developer-machine directory.
- For shared harmonic-selection changes, run both `publication-maps` and
  `stats`. For shared figure-style changes, run `figures` plus the affected
  tool scope.
- When a GUI behavior cannot be exercised locally, report the CI target and a
  concrete visible/manual smoke path instead of substituting an offscreen run.

## Removed Source Localization

Source Localization/eLORETA remains removed from active runtime. Do not add
tests that import `Tools.SourceLocalization`, restore availability shims, or
require bundled fsaverage MRI/template data. The separate LORETA Visualizer
uses the `loreta` scope and its local boundary contract.
