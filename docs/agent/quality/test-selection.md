# Test Selection

Use the repository verification driver as the executable source of truth. It
selects `.venv1` or `.venv`, keeps output compact, applies the explicit Qt-test
registry, and composes the tests, audits, compilation, and lint checks required
for each scope.

```console
python .agents/scripts/verify.py --scope <scope> --tier focused
```

Run `python .agents/scripts/verify.py --scope repo --tier precommit` for the
broad local handoff gate. Do not duplicate its pytest lists in documentation;
update `.agents/verification.toml` when executable coverage changes and
`tests/qt_test_files.txt` when Qt dependencies change. Check both with
`python .agents/scripts/verify.py --check-config`.

Application verification excludes `tests/standalone_scripts` from broad local
precommit and CI runs because those tests import the opt-in
`src/Standalone_Scripts` utilities. Run standalone-script tests separately only
when the user explicitly scopes that directory or approves access, following
its scoped `AGENTS.md`. Routine application tests must not collect that suite.
Default Ruff discovery also excludes these opt-in utilities and their tests;
Stats remains part of the active application lint baseline.

## Qt Execution Boundary

PySide6/pytest-qt tests are CI-only by default. Do not run them on local
development machines, do not set `QT_QPA_PLATFORM=offscreen`, and do not
launch ad-hoc offscreen Qt scripts. They can freeze indefinitely even when a filename or
marker does not obviously identify it as a Qt test.

For GUI changes, keep the CI Qt coverage definition current, run the local
focused scope for non-GUI checks, and document a visible/manual smoke path. Run
Qt tests locally only when the user explicitly approves a safe visible GUI
environment.

## Scope Map

| Scope | Local focused coverage | Qt coverage retained for CI |
| --- | --- | --- |
| `backend-hardening` | Canonical import boundaries, settings/persistence, transaction recovery, runner lifecycle, exact spectral reads and source-model caches | None in this local bundle |
| `gui` | GUI import boundaries, syntax/static checks, non-window contracts | Main-window layout/wiring, stable/beta visibility, per-tool beta acknowledgement, dialogs, settings/status, embedded-page smoke |
| `updates` | Release selection, download/install backend, packaging syntax, GUI-module compilation | Update dialog and manager interaction |
| `project-io` | Project settings, acquisition profiles and source formats, BIDS import, enumeration/scanning, result paths, manifest contracts, shared exact XLSX reading | File dialogs and visible project workflows |
| `processing` | Shared MNE admission, acquisition policy, order/fingerprint, QC calibration, persistence, FFT crop, runner/export contracts | Processing-window wiring and Qt workers |
| `plot-generator` | Excel/config helpers, aggregation, FFT/SNR behavior, rendering and export contracts | Plot Generator page/layout/workflow smoke |
| `publication-maps` | Processing-time harmonics, BCA/SNR rendering, figure-only paired/group outputs, colorbars | Embedded Scalp Maps page behavior |
| `sequence-figure` | Renderer behavior and high-DPI outputs | Embedded Sequence Figure wiring |
| `sensitivity-analysis` | Paired-test/RM-ANOVA power math plus mixed-model simulation, search, cancellation, uncertainty, and validation | Embedded page wiring, background worker, controls, results, reset, information tabs, and clipping smoke |
| `stats` | Data/project context, pipeline, DV/harmonic rules, FullSNR, exports and reporting | Stats layout, focus, and window workflow smoke |
| `free-harmonic-clustering` | FullFFT selected reads, spectral preparation, adjacency, paired/independent permutation inference, Excel/run-bundle exports, and static embedded-GUI contracts | Open the tool visibly from the default Quick Tools list, exercise prepare/run/cancel/results/folder actions, and preserve the documented optional human acceptance path; pytest-qt remains CI-only locally |
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

## Maintaining older tests

Retirement names are not sufficient grounds for deletion. Keep scientific
baselines, historical-project/schema behavior, compatibility-alias identity,
and guards against reintroducing retired GUI packages. Ordinary tests should
import current implementation owners; only explicit compatibility tests should
exercise transitional aliases.

Remove migration-only symbol checks when current behavioral tests cover the
same contract. Refresh reader mocks at the current public boundary instead of
weakening assertions to accommodate a new implementation. Do not catch every
import error and skip: a supported import failing is a regression. Split
backend and Qt-dependent tests when possible so the backend coverage runs
locally. Keep the scope map and Qt registry aligned with file moves/removals.

## Hardware and Studio extension coverage

The [roadmap](../architecture/hardware-pipeline-studio-roadmap.md) owns future
acceptance criteria. Existing acquisition-profile and BDF/Studio inspection
fixtures live under project I/O; production stage selection also requires
processing, provenance/cache and affected downstream-consumer coverage.
An inspection fixture passing for a third profile does not establish an
extensible production pipeline. Keep hardware/timing validation separate from
synthetic tests and do not promote unqualified support through documentation.

## Retired Source Localization package

The retired `Tools.SourceLocalization` package and its old eLORETA runtime
remain removed. Do not add tests that import that package, restore its
availability shims, or require bundled fsaverage MRI/template data.

The separate, current `Tools.LORETA_Visualizer` owns its visualization workflow
and isolated source producers under its scoped architecture contract. Its
existing L2-MNE/eLORETA producers are supported by the `loreta` verification
scope; this boundary does not prohibit their current tests or imply that those
producers must be removed. Keep numerical producer code separate from rendering
and GUI code, and preserve the ignored root `.fpvs_cache` dependency cache.
