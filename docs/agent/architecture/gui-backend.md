# Desktop workflows and backend ownership

Use this guide when a Toolbox GUI change touches a project rule, a processing
decision or a file export. As in Studio, the desktop captures choices and
passes ordinary Python values to the project, processing or tool module.
Each operation has a direct test entry
point independent of the window.

## What Studio separates

The same split reaches experiment execution. The GUI requests compilation of
an editable project. Core builds a `SessionPlan`, and runtime consumes the plan.
That gives scheduling one owner and lets a compiler test exercise it without
opening Studio. [Studio architecture and contract flow](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/ARCHITECTURE.md)

| Workflow | What the GUI owns | What crosses into the backend |
| --- | --- | --- |
| Image Equalizer | The dialog captures the selected folders once, starts a task and presents progress, errors and results. | A tuple of folder pairs, a cancellation check and a progress callback. The backend validates images, writes files, cleans up its own outputs on cancellation and returns an `ImageEqualizationResult`. [Dialog](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/src/fpvs_studio/gui/image_equalizer_dialog.py#L214) · [Operation](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/src/fpvs_studio/preprocessing/equalization.py#L193) |
| Open Project | The controller tracks which request is current. Only its accepted completion can replace the visible document. | The background task returns the project root and loaded models. A failed or superseded read leaves the displayed project in place. [Controller](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/src/fpvs_studio/gui/controller.py#L957) · [Failure, cancellation and draft tests](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/tests/gui/test_frontend_responsiveness.py) |

Studio's dependency tests check selected import directions and load named
backends in a fresh interpreter. Its controller still handles some filesystem
operations, including project deletion. Use the tested separation of a
specific operation as the precedent. [Dependency tests](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/tests/unit/test_import_boundaries.py) · [Project deletion](https://github.com/zcm58/FPVS-Studio-2.0/blob/fd20fa308f03c987534564f50c2df66381eb5235/src/fpvs_studio/gui/controller.py#L1816)

## Where Toolbox already does this

Follow **Experiment Library → Download and open** end to end. The page emits
the user's action. `ExperimentLibraryController` captures the selected item
and projects root. `ExperimentInstallWorker` translates phase, progress and
cancellation between Qt and `install_public_dataset`. The project module
verifies and installs the archive. The controller receives the installed path
and decides whether it may open the project. A late cancellation can leave a
valid installation available for later opening. [Page](../../../src/Main_App/gui/experiment_library_page.py) · [Controller](../../../src/Main_App/gui/experiment_library_workflow.py) · [Worker](../../../src/Main_App/workers/experiment_library_worker.py) · [Installation](../../../src/Main_App/projects/experiment_library.py) · [Guard tests](../../../tests/gui/test_experiment_library_workflow_static.py)

This makes the ownership decision concrete. Capture choices, focus, prompts
and navigation in the GUI. Put project validation and publication in
`Main_App.projects`, EEG decisions in `Main_App.processing`, and a tool's
export in its own backend. When long work is involved, reuse its existing
worker and completion path. A short operation on ordinary values can remain
a direct function call. [Worker lifetimes](workers-threading.md)

## Toolbox workflow owners

**1. Sequence Figure.** The page builds a `SequenceFigureSpec`, and the worker
calls `render_sequence_figure`. The package exports the renderer, spec and result
without loading Qt. Looking up `SequenceFigureWindow` loads the GUI class on
demand. The beta menu still opens that same class. [Package initializer](../../../src/Tools/Sequence_Figure/__init__.py) · [Import tests](../../../tests/audit/test_backend_import_boundaries.py) · [Renderer tests](../../../tests/sequence_figure/test_sequence_figure_renderer.py) · [Project-switch smoke](../../../src/Tools/Sequence_Figure/AGENTS.md)

**2. Repeated-session setup.** The Qt-free project setup module owns session
IDs, manifest construction, and application of the accepted source preflight
report. The project manager retains its existing entry points, folder prompts,
worker lifetime, cancellation and activation. Check source IDs and visit order
in the returned manifest, rejection of a missing cell or reused folder, and
the accepted empty scaffold. [Project setup](project-io.md#repeated-session-setup) · [Setup cases](../../../tests/project_io/test_repeated_session_project_setup.py) · [Qt continuation and cancellation](../../../tests/project_io/test_repeated_session_project_setup_qt.py)

**3. Individual Detectability.** `run_detectability_export` takes a
`RunRequest` and ordinary log, status and progress callbacks. It binds
managed inputs, resolves harmonics and prevalidates the full selection before
opening the log or writing figures. A successful return identifies the output
root, including when all inputs are excluded. The worker translates that
return or an exception into the page's existing signals. [Export operation](../../../src/Tools/Individual_Detectability/export_run.py) · [Worker](../../../src/Tools/Individual_Detectability/worker.py) · [Coverage tests](../../../tests/processing/test_individual_detectability_project_coverage.py) · [Tool contract and smoke](../../../src/Tools/Individual_Detectability/AGENTS.md)

**4. Processing preflight.** After a user chooses a reprocessing scope,
`processing_ledger.additional_preflight_infos_for_chosen_scope` returns the
selected recordings that still need QC-19 marker review. The GUI opens the
review only for those files, preserves prior plans and stops the launch on
cancellation. See the preflight section of the processing contract for the
exclusion and lookup rules. [Processing contract](preprocessing-contract.md)
[Plan owner](../../../src/Main_App/processing/processing_ledger.py) · [Plan tests](../../../tests/processing/test_expected_processing_ledger.py) · [GUI handoff tests](../../../tests/gui/test_recording_qc_static_contracts.py)

## Verification for a port

1. Start with the public entry point. For a Qt-free module, add its normal
   dotted import to the existing fresh-interpreter test. Package initializers
   count. For a moved decision, call it directly with the same inputs as the
   desktop path and compare its results, errors and write timing.
2. Exercise the original user action through its registered Qt test in CI or
   its approved visible smoke path. Check guard and draft behavior, failure
   and retry, cancellation, late results and project switching where the
   workflow supports them. Use the owning tool's existing acceptance cases.
3. Run the affected focused scope and the repository handoff gate. Project
   schemas, recording identities, scientific order, fingerprints and exports
   follow their current contracts throughout the extraction. [Scope map](../quality/test-selection.md#scope-map) · [Product acceptance](../product-specs/fpvs-toolbox.md#desktop-workflow-compatibility)
