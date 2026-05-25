# v2.1 Processing Workflow

## Status

Active planning and implementation plan. Created on 2026-05-24.

This plan captures the v2.1 processing workflow decisions before code changes.
Keep it current as new decisions are made. Future agents should read this plan
before changing project setup, project manifests, raw-file discovery, single-file
or batch processing, Excel output layout, processing ledger behavior, Plot
Generator multi-group support, or Stats-ready group metadata.

## Goal

Make FPVS Toolbox v2.1 a production-ready processing workflow release for both
common single-group studies and true multi-group studies.

The release should let users:

- define multi-group projects from pre-separated raw `.bdf` folders;
- keep participant group assignment canonical in `project.json`;
- lock group definitions after first successful processing;
- add later-recorded participants by placing `.bdf` files into registered raw
  folders;
- process incrementally by default while still offering a clear reprocess-all
  path;
- share one canonical processing pipeline between single-file and batch modes;
- produce Excel output trees that are predictable for humans and downstream
  tools.

## Non-Goals

- Do not change preprocessing math, event detection, epoching, FFT, SNR, BCA,
  workbook sheet schemas, or Stats DV definitions unless a later slice
  explicitly proves a bug.
- Do not make single-file processing a separate diagnostic sandbox in v2.1.
- Do not add backward-compatible flat-reader fallbacks for new multi-group
  projects. Users will reprocess into the v2.1 layout.
- Do not silently infer group assignment from Excel output folders.
- Do not silently move or repair mismatched group output files.
- Do not run offscreen Qt workflows locally.

## Terminology

- File execution mode: `Single` or `Batch`.
  - `Single` means the user selects one `.bdf`; the backend runner may still use
    the batch/process-runner path with one worker.
  - `Batch` means the app discovers all registered raw `.bdf` files for the
    active project.
- Project grouping mode: single-group/ungrouped project or true multi-group
  project.
  - This controls manifest schema, participant group assignment, output layout,
    validation, and group locking.
  - It must not be coupled to file execution mode.

## Locked Decisions

1. v2.1 should finalize end-to-end multi-group workflow support, not only Plot
   Generator cleanup.
2. Multi-group users must separate `.bdf` files into group-specific raw folders
   before project setup.
3. Multi-group setup registers one raw input folder per group.
4. The raw folder name becomes the default group label and output folder name,
   with user edits allowed before the project is processed.
5. `project.json` is canonical for group definitions and participant group
   assignment.
6. Each multi-group participant gets an explicit stored group assignment based
   on the user-defined group folder that contained the participant's `.bdf`.
7. Stable internal group IDs should be used for durable references; user-facing
   labels and output folder names are separate fields.
8. Multi-group Excel output layout is condition-first, group-second:

   ```text
   1 - Excel Data Files/
     <Condition>/
       <Group>/
         <Participant>_<Condition>_Results.xlsx
   ```

9. Single-group Excel output keeps the existing flat condition layout:

   ```text
   1 - Excel Data Files/
     <Condition>/
       <Participant>_<Condition>_Results.xlsx
   ```

10. Group definitions lock after the first successful canonical processing run.
11. After group definitions lock, users cannot casually edit groups or existing
    participant group assignments.
12. To change group definitions after lock, users create a new project and
    reprocess.
13. New participants may be added to locked projects when their `.bdf` files
    appear inside already-registered raw folders.
14. New participant additions require a review step before processing.
15. Incremental processing applies to both single-group and multi-group
    projects.
16. Batch mode defaults to processing only new or changed files.
17. Before batch processing, show a modal choice when existing completed outputs
    are detected:

    ```text
    FPVS Toolbox found 28 BDF files in this project.

    25 files already have completed outputs for the current project settings.
    3 files have not been processed yet.

    What would you like to process?
    ```

    Primary/default action when settings match: process new or changed files
    only. Secondary action: reprocess all. Cancel remains available.

18. If processing settings changed since earlier runs, strongly recommend
    reprocessing all files and explain why mixed settings can invalidate group
    comparisons.
19. Settings-change dialog should still allow incremental processing, but
    `Reprocess All Files` is the default/focused action.
20. The user's processing choice must be logged.
21. "Already processed" requires both ledger evidence and expected Excel output
    files on disk.
22. Expected Excel output verification is strict per configured condition.
23. Multi-group skip eligibility also requires outputs to exist under the
    participant's canonical group folder.
24. Outputs for a participant under the wrong group folder are a hard validation
    error. The app should block and ask the user to resolve the mismatch.
25. `Reprocess All` cleans and recreates the managed Excel output tree for both
    single-group and multi-group projects.
26. Files inside the managed Excel output tree may be deleted during
    `Reprocess All`; the confirmation must say this clearly.
27. Files outside the managed Excel output tree are not touched.
28. Processing ledger state lives in a generated project-local folder, not in
    `project.json`.
29. Single-file and batch modes share the canonical processing pipeline.
30. Single-file mode differs from batch mode only by file selection and worker
    count.
31. Single-file mode must validate that the selected `.bdf` belongs to the
    active project's registered raw-data source.
32. For multi-group projects, a single-file selection must belong to one
    registered group raw folder.
33. For single-group projects, a single-file selection must belong to the
    project input folder.
34. A successful single-file run writes canonical outputs, updates the same
    processing ledger, and may be skipped by a later batch run when the ledger,
    raw-file metadata, settings fingerprint, expected outputs, and group
    assignment still match.
35. `.fpvs_processing/` is generated recovery state, not normal user-facing
    project configuration. Users are not encouraged to delete it, but if it is
    missing or invalid, FPVS Toolbox recreates it and falls back to conservative
    processing decisions.
36. For `group_count == 1`, v2.1 writes no `groups` metadata. `project.groups`
    is reserved for true multi-group projects with two or more experimental
    groups.
37. Newly discovered participants require a modal review table before being
    added to `project.json`.
38. The participant review table shows one row per newly discovered participant
    with participant ID, group label, raw file path, and status.
39. The participant review modal actions are `Add Participants and Continue`
    and `Cancel`.
40. If duplicate or conflicting participant assignments are detected, the
    review modal disables continue and explains the conflict so the user can
    move or rename files before processing.
41. Group IDs are generated as readable slugs from the chosen group folder or
    label, with deterministic collision suffixes such as `control_group_2`.
42. Do not use hidden UUID-like group IDs for v2.1; readable slugs make
    `project.json`, logs, Stats exports, and support/debugging easier.
43. `Reprocess All` cleans the entire managed Excel root,
    `1 - Excel Data Files/`, after confirmation. This includes generated
    condition folders that are no longer configured, so stale condition outputs
    cannot survive and be consumed by downstream tools.
44. The same inferred participant ID cannot contribute more than one `.bdf`
    file to a project.
45. Duplicate inferred participant IDs hard-block processing whether they appear
    in the same raw folder or across different group folders.
46. Multi-run or multi-session merging is out of scope for v2.1 and should be a
    separate future feature if needed.
47. If an existing participant's `.bdf` appears in a different registered group
    folder after group assignments are locked, processing hard-blocks.
48. Do not auto-update an existing participant's `group_id` after lock. Changing
    an existing participant's group requires creating a new project and
    reprocessing.

## Current Repo Evidence

- Project setup already asks for the number of experimental groups in
  `src/Main_App/projects/project_manager.py`.
- Current setup collects a group name and raw input folder for each configured
  group.
- Current `Project` persistence stores `groups` keyed by group display name and
  `participants` entries with `group`, not stable `group_id`.
- Current batch preparation treats any non-empty `project.groups` as grouped
  discovery.
- Current project load can call batch preparation and update participants
  before an explicit review step.
- Current grouped discovery can fall back to the single input folder path, which
  conflicts with the v2.1 no-silent-fallback direction for multi-group projects.
- Current Excel export writes condition folders directly under
  `1 - Excel Data Files` and does not add a group subfolder.
- The GUI and runner already compute preprocessing/settings fingerprints; reuse
  that concept for ledger staleness instead of inventing a separate settings
  comparator.

## Proposed Manifest Shape

The exact schema should be finalized in an implementation slice, but the target
shape is:

```json
{
  "schema_version": "2.1.0",
  "groups_locked": true,
  "groups_locked_at": "2026-05-24T00:00:00Z",
  "groups": {
    "control": {
      "label": "Control",
      "folder_name": "Control",
      "raw_input_folder": "D:/EEG_Data/MyStudy/Control"
    },
    "treatment": {
      "label": "Treatment",
      "folder_name": "Treatment",
      "raw_input_folder": "D:/EEG_Data/MyStudy/Treatment"
    }
  },
  "participants": {
    "P01": {
      "group_id": "control",
      "raw_file": "D:/EEG_Data/MyStudy/Control/P01.bdf"
    }
  }
}
```

Rules:

- `group_id` is the stable internal key.
- `group_id` is a readable slug generated from the selected group folder or
  label, with deterministic suffixes for collisions.
- `label` is user-facing.
- `folder_name` controls Excel output paths.
- `raw_input_folder` may live outside the Toolbox project folder.
- Participant records point to `group_id`, not to `label` or `folder_name`.
- Folder names must be unique, non-empty, and safe for Windows paths.
- Do not silently sanitize a group folder name after creation in a way that
  changes the user's intended grouping.

## Proposed Processing State Shape

Store generated run state under the active project root:

```text
.fpvs_processing/
  processing_ledger.json
  processing_runs.jsonl
```

Responsibilities:

- `project.json`: durable project identity, raw input folder(s), group
  definitions, participant assignments, and group lock state.
- `processing_ledger.json`: per participant/file completion state, raw path,
  raw size and mtime, settings fingerprint, expected output paths, completion
  status, and run mode that produced the current completion.
- `processing_runs.jsonl`: append-only run history with run mode, user choice,
  settings-change warnings, counts for skipped/new/stale/processed/failed files,
  and timestamps.
- `.fpvs_processing/`: generated project-local state. It is useful for
  incremental processing and support/debugging, but `project.json` remains the
  canonical project manifest. If this folder is deleted or corrupted, the app
  should recreate it and reprocess unless existing outputs can be strictly
  verified.

## Open Decisions

No open decisions are currently locked for this planning pass. Add new items
here as the design tree expands.

## Suggested Slices

### Slice 1 - Project Model And Schema

Goal: make the manifest capable of representing v2.1 grouping without changing
processing behavior yet.

Tasks:

- Add normalization/persistence for group `label`, `folder_name`,
  `raw_input_folder`, and participant `group_id`.
- Preserve current manifests where possible during load, but do not add silent
  fallback behavior for new v2.1 multi-group projects.
- Add group lock fields to the project model.
- Implement the single-group manifest rule.
- Add slug-based group ID generation with collision suffixes.
- Add focused project I/O tests.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\projects\project.py src\Main_App\projects\project_manager.py
.\.venv1\Scripts\python.exe -m pytest tests\project_io -q
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

### Slice 2 - Setup And Participant Review

Goal: make project setup and later discovery assign participants through an
explicit review step.

Tasks:

- Update multi-group setup to default labels/folder names from selected raw
  folders.
- Validate group folder names and duplicate groups.
- Add or reuse a review surface for discovered participants before writing new
  participant assignments. The review surface must list participant ID, group
  label, raw file path, and status, with `Add Participants and Continue` and
  `Cancel` actions.
- Ensure locked projects can add new participants only from registered folders.
- Ensure group edits are blocked after lock.
- Ensure existing participant assignments cannot drift when files are moved
  between group folders after lock.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\projects\project_manager.py src\Main_App\gui\project_workflows.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

Do not run offscreen Qt locally. Document a visible/manual setup smoke path.

### Slice 3 - Discovery And Validation

Goal: make raw-file discovery strict, reviewed, and uncoupled from output
folders.

Tasks:

- Split execution mode from project grouping mode in discovery helpers.
- Remove silent multi-group fallback to single input folder.
- Detect duplicate participant IDs across group folders and block processing.
- Detect duplicate participant IDs within the same raw folder and block
  processing.
- Require single-file selections to come from registered raw sources.
- Keep single-file mode and batch mode on the same backend pipeline.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\processing\processing_controller.py src\Main_App\gui\processing_inputs.py
.\.venv1\Scripts\python.exe -m pytest tests\processing tests\project_io -q
```

### Slice 4 - Processing Ledger And Incremental Planner

Goal: decide which files should run before the runner starts.

Tasks:

- Add `.fpvs_processing/processing_ledger.json`.
- Add `.fpvs_processing/processing_runs.jsonl`.
- Reuse the existing preprocessing/settings fingerprint concept.
- Classify discovered files as completed, missing, stale, changed settings,
  missing outputs, or invalid layout.
- Show the pre-run modal for incremental versus reprocess-all.
- Log the user's choice and counts.
- Make single-file successful runs update the same ledger.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\processing_inputs.py src\Main_App\gui\processing_workflows.py src\Main_App\workers\mp_runner_bridge.py
.\.venv1\Scripts\python.exe -m pytest tests\processing -q
```

### Slice 5 - Excel Output Layout And Cleanup

Goal: write outputs to the correct managed tree and make reprocess-all clean.

Tasks:

- Keep single-group outputs flat by condition.
- Write multi-group outputs under condition/group folders.
- Validate that existing outputs do not conflict with `project.json`.
- Implement managed-tree cleanup for `Reprocess All` for both project types.
- Ensure cleanup is limited to the generated `1 - Excel Data Files/` root and
  does not touch unrelated project folders.
- Make confirmation text explicit about deleting files in the managed tree.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\Shared\post_process.py src\Main_App\Performance\process_runner.py
.\.venv1\Scripts\python.exe -m pytest tests\processing tests\project_io -q
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

### Slice 6 - Downstream Tool Alignment

Goal: make Plot Generator and Stats consume the v2.1 manifest/output contract.

Tasks:

- Update Plot Generator manifest helpers to read participant `group_id` and
  resolve labels/folder names.
- Update Plot Generator multi-group SNR plan if its assumptions change.
- Update Stats participant mapping to use v2.1 group IDs while preserving the
  single-group fallback.
- Ensure tools do not infer group assignment from output folder names except as
  validation evidence against `project.json`.

Verification:

```powershell
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator tests\stats -q
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-structure
```

### Slice 7 - Docs And Release Readiness

Goal: make user and agent docs match the implemented workflow.

Tasks:

- Update user project setup docs with raw-folder preparation guidance.
- Update processing-pipeline docs with incremental/reprocess-all behavior.
- Update output-reference docs with single-group and multi-group trees.
- Update `docs/agent/architecture/project-io.md`.
- Update `docs/agent/architecture/post-processing-export-contract.md` if output
  layout ownership changes.
- Update `docs/agent/quality/test-selection.md` with focused tests.
- Move this plan to `completed/` only after all slices are implemented and
  verified.

Verification:

```powershell
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
.\.venv1\Scripts\python.exe -m mkdocs build --strict
```

## Update Protocol

When a new decision is made:

1. Add it to `## Locked Decisions` if accepted.
2. Remove or revise any conflicting item in `## Open Decisions`.
3. Update the relevant slice tasks if the decision changes implementation
   order.
4. Append a short entry to `## Progress Log`.

After each implementation slice:

1. Mark the slice status in this plan.
2. List touched files.
3. Record verification commands and results.
4. Record skipped GUI/manual smoke checks and residual risk.
5. Stop unless the user explicitly asked to continue through more slices.

## Progress Log

### 2026-05-24 - Plan Created

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decisions captured: folder-defined multi-group setup, canonical
  `project.json` assignments, post-processing group lock, incremental
  processing, reprocess-all cleanup, strict expected-output verification, and
  single-file/batch pipeline alignment.
- Open items kept explicit: generated-state deletion behavior, exact
  single-group manifest shape, participant review UI, group ID generation, and
  cleanup boundaries for removed conditions.

### 2026-05-24 - Processing State Recoverability Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: `.fpvs_processing/` is generated recovery state, not normal
  user-facing project configuration. If it is deleted or invalid, FPVS Toolbox
  should recreate it and make conservative processing decisions rather than
  treating the project as damaged.

### 2026-05-24 - Single-Group Manifest Shape Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: one-group projects write no `groups` metadata. `project.groups` is
  reserved for true multi-group projects so ordinary one-group batch workflows
  keep the flat output layout and do not look like grouped studies to
  downstream tools.

### 2026-05-24 - Participant Review UI Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: newly discovered participants are added to `project.json` only
  after a modal review table lists participant ID, group label, raw file path,
  and status. The modal offers `Add Participants and Continue` and `Cancel`;
  conflicts disable continue and explain the required user cleanup.

### 2026-05-24 - Group ID Generation Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: v2.1 group IDs are readable slugs generated from the selected group
  folder or label, with deterministic collision suffixes. Hidden UUID-like
  group IDs are out of scope for v2.1.

### 2026-05-24 - Reprocess-All Cleanup Boundary Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: `Reprocess All` cleans the entire generated
  `1 - Excel Data Files/` root after confirmation, including stale condition
  folders no longer present in `event_map`. Cleanup must not touch unrelated
  project folders.

### 2026-05-24 - Duplicate Participant ID Rule Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: the same inferred participant ID cannot contribute more than one
  `.bdf` file to any project. Duplicate IDs hard-block processing whether they
  appear in the same raw folder or across group folders. Multi-run/session
  merging is out of scope for v2.1.

### 2026-05-24 - Moved Participant After Lock Rule Locked

- Status: active planning.
- Files changed: `docs/agent/exec-plans/active/v2-1-processing-workflow.md`.
- Decision: if an existing participant appears in a different registered group
  folder after group assignments are locked, processing hard-blocks. The app
  must not auto-update the participant's `group_id`; changing group assignment
  requires a new project and reprocessing.
