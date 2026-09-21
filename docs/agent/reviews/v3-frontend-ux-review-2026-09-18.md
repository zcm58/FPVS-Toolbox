# v3 frontend user-experience review

Date: 2026-09-18. Review branch: `codex/v3-frontend-ux-review`.
Baseline: `codex/v3-release` at `d6dbd474d1f6d649cf515556307af35b630bd5d4`.
Status: all nine recommendations were implemented and verified on 2026-09-19.
The changes are prepared for the frontend branch only. See the
[implementation and verification record](#implementation-and-verification-record).
The findings describe the reviewed baseline; evidence line numbers refer to that
baseline, not the implementation.

## Scope and evidence

Reviewed the active PySide6 project/setup and processing journey, Settings,
preprocessing and frequency-domain QC reviews, shared controls, and the two
default v3 tools: Free Harmonic Clustering (FHC) and SNR Plots. This is a
source-backed interaction review, not a complete visual audit of every beta
tool. Scientific methods, processing order, output data formats, and recorded
EEG marker interpretation remain outside the proposed changes. FPVS Toolbox
does not send triggers.

Ranking prioritizes unintended setup changes and loss of work, then blocked
tasks, outcome clarity, and repeated navigation effort. The design basis is
error prevention, user control, visible system state, and actionable recovery,
as described in [Nielsen's usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).
Keyboard/focus acceptance should follow [Qt's widget focus guidance](https://doc.qt.io/qt-6/focus.html).
These principles guide the proposals; the repository evidence establishes the
specific findings. Impact estimates are engineering judgments, not measurements
from a participant usability study.

## Ranked recommendations

### 1. Validate every condition row before Save or Start — high priority

**Problem.** Incomplete condition rows can be silently omitted. Repeated names
overwrite earlier entries in the name-keyed mapping. For example, `Faces=1`
and `Objects=<blank>` save only Faces; `Faces=1` and `Faces=2` save only the
second Faces entry. Save still reports that all settings were written. Start
readiness requires only one complete row, and processing collects rows with
the same omission/overwrite behavior.

**Evidence.** `src/Main_App/gui/project_workflows.py:655-698`;
`src/Main_App/gui/processing_inputs.py:598-637`;
`src/Main_App/gui/event_map.py:129-142`. The two Save examples were reproduced
by executing the actual function extracted through AST with widget-free doubles.

**Proposed fix.** Use one validation result for Save and Start. Allow an entirely
empty placeholder row, but flag partially filled rows and duplicate names next
to the affected fields. Keep the entries intact, focus the first problem, and
prevent committing the incomplete mapping. Preserve current marker semantics.

**User benefit.** The saved and processed conditions match what the user intended;
an apparently successful save cannot quietly hide a setup mistake.

**Acceptance.** Partial and duplicate rows block Save/Start with an identifiable
field error; correcting them clears the error. A fully empty extra row remains
harmless, and a valid multi-condition setup saves without an extra dialog.

### 2. Ask before replacing existing SNR figures — high priority

**Problem.** Repeating a condition/ROI export can write the same PNG/PDF paths.
The naming helper prevents name clashes within a rendering run, but does not
protect files from earlier runs. Experimenting with axes, colors, or groups can
therefore replace a previously preferred figure without a replacement decision.

**Evidence.** `src/Tools/Plot_Generator/render_naming.py:44-79` tracks an
in-memory set; `src/Tools/Plot_Generator/rendering.py:324-342` writes directly
to the resulting filenames. A read-only helper probe confirmed identical names
from separate worker-like objects. No existing figures were overwritten in this review.

**Proposed fix.** Only when destinations already exist, show one collision
summary with **Replace existing**, **Keep both**, and **Cancel**. Treat PNG/PDF
as a pair, suffix only a Keep both copy, and preserve the current flat output
folder and ordinary filenames. Use a safe default and keep export work off the
UI thread. Avoid a new export-management screen or per-run folders.

**User benefit.** Users can try variations while deliberately controlling which
previous outputs they replace.

**Acceptance.** Export twice to the same destination; Cancel changes neither
file, Keep both preserves both matching pairs, and Replace changes only the
explicitly approved pair(s). A collision-free export adds no confirmation.

### 3. Protect unsaved setup and QC decisions at real discard points — high priority

**Problem.** Project replacement or application exit has no general unsaved
setup check. Lengthy QC reviews can also be dismissed with current decisions
still unapplied. Frequency QC already says that choices are unsaved and its
Cancel tooltip explains discard, but accidental Escape/window close still
lacks a conditional safeguard.

**Evidence.** `src/Main_App/gui/main_window.py:1021-1162` guards active work,
not dirty drafts; `src/Main_App/gui/project_workflows.py:478-505` retires the
Settings page on project replacement. Frequency QC directly connects Cancel to
reject at `src/Main_App/gui/frequency_domain_qc_dialog.py:346-355`;
`src/Main_App/gui/kurtosis_review_dialog.py:707-713` also dismisses without a
dirty-choice check. Ordinary sidebar navigation already retains Settings
(`src/Main_App/gui/main_window.py:448-465`) and should stay uninterrupted.

**Proposed fix.** Show an unobtrusive unsaved-state indicator. Before replacing
the project or exiting with a changed setup, offer **Save / Discard / Cancel**.
For changed QC choices, use **Keep reviewing / Discard choices** at dismissal.
Do not prompt for unchanged forms and do not auto-apply scientific decisions.
Keep the existing explicit Apply requirement and preserve normal page navigation.

**User benefit.** Prevents losing setup or review effort through a stray close
action, without slowing routine navigation.

**Acceptance.** Edit conditions/Settings then change project or quit; verify
each choice and ensure failed validation prevents Save-and-leave. Dismiss a
partly completed QC review with Escape/X and confirm Keep reviewing restores
the exact in-memory choices. Unchanged reviews close directly.

### 4. Keep single-file selection consistent after processing — medium priority

**Problem.** Finalization clears `data_paths`, while the selected filename
remains visible. Start readiness checks the visible filename; launch validation
checks `data_paths`. A user can therefore see a valid selected file and enabled
Start, then receive "No File Selected" when attempting another run.

**Evidence.** `src/Main_App/gui/processing_completion.py:64`;
`src/Main_App/gui/processing_inputs.py:161-165,863-871`. A widget-free execution
of the actual finalizer confirmed the visible filename survives while the
internal selection becomes empty.

**Proposed fix.** Prefer retaining the selected recording for another run.
Derive the visible field, readiness, and launch validation from the same
selection. If clearing is required, clear the field and disable Start together.

**User benefit.** The next click behaves as the screen promises, and users do
not have to reselect a recording that still appears selected.

**Acceptance.** Finish a single-file run and immediately start another. Verify
consistent behavior after success/failure and when the underlying file is removed.

### 5. Explain disabled analysis actions where the user needs the answer — medium priority

**Problem.** Some invalid configurations disable Run/Generate without showing
the reason. SNR silently disables an overlay of a condition with itself; it
also computes informational missing-input messages and then hides them. FHC
computes setup errors such as selecting the same independent group twice, but
its button update uses the error only to decide enabled state.

**Evidence.** `src/Tools/Plot_Generator/gui.py:338-382`;
`src/Tools/Free_Harmonic_Clustering/gui/page.py:1019-1020,1084-1098,1667-1673`.
A widget-free execution of the SNR method confirmed Generate is disabled and
status hidden for identical overlay conditions.

**Proposed fix.** Display the first actionable reason beside the action, such
as "Choose two different conditions," and identify the relevant control.
Remove the message when corrected. Reuse existing status components and
validation results; do not automatically change the user's analysis selections.
Apply the same pattern to missing prerequisites beside Start Processing.

**User benefit.** Users can fix the setup immediately instead of guessing why
the application will not let them proceed.

**Acceptance.** Test missing inputs and duplicate comparison selections with
mouse and keyboard. The reason must be visible without hovering over a disabled
button and must clear as soon as the setup becomes valid.

### 6. Replace disruptive Settings validation with field-level guidance — medium priority

**Problem.** Leaving any preprocessing text field validates the entire
preprocessing/harmonic payload. Invalid values raise a modal warning and return
focus; leaving the Preprocessing tab also invokes validation and can switch
back. This interrupts multi-field edits and can report an error outside the
field the user was just editing.

**Evidence.** `src/Main_App/gui/settings_panel.py:568-571,3464-3478,3554-3603`.
The current general focus helper recognizes only selected preprocessing error
names (`3483-3495`); other sections already provide more specific field focus.

**Proposed fix.** Show a concise inline message for an edited invalid field.
Allow intermediate values and movement to other fields/tabs. Keep strict
whole-form validation at Save or another committing action, then select the
relevant tab and first invalid control. Preserve all accepted values and
scientific validation rules; change when and where errors are presented.

**User benefit.** Users can finish entering related settings without repeated
interruptions, while invalid settings still cannot be saved or used.

**Acceptance.** Temporarily clear a number, move between fields/tabs, then
correct it without a modal loop. Save with an invalid field on another tab must
locate that exact field. Cancel must remain usable.

### 7. Retain a compact last-run outcome with useful next actions — medium priority

**Problem.** Finalization leaves the processing activity page and resets
progress. Success and exclusion/condition-warning summaries appear in separate
dismissible dialogs; cancellation is logged. Once those dialogs are gone,
users returning to the app must reconstruct the outcome from logs or outputs.
Existing reports and incomplete-post-processing messages are valuable, but are
not a persistent, compact last-run overview.

**Evidence.** `src/Main_App/gui/processing_workflows.py:547-594,2072-2088`;
`src/Main_App/gui/shell_status.py:567-595`;
`src/Main_App/gui/processing_completion.py:14-45`.

**Proposed fix.** Keep a small last-run summary visible in the existing workflow,
with actual completed/excluded/failed counts and separate condition-level
warnings where relevant. Distinguish cancelled, incomplete, and complete states.
Offer **Open Output Folder**, **Review Issues**, and the existing **View Log**.
Derive counts from established outcomes, not the initial file count, and link
to the existing evidence rather than duplicating it. No historical-run browser
or new dashboard is necessary.

**User benefit.** Users can see what finished and what to do next after a long
run, without keeping several message boxes in memory.

**Acceptance.** Complete, exclude part of, fail, and cancel small test runs.
Verify the persistent summary matches actual outcomes and never labels
incomplete post-processing as ready. Links must target the active project.

### 8. Lead interpolation-burden reviewers to unfinished decisions — medium priority

**Problem.** This review puts each recording's choices and reasons in a table.
When Apply finds an unresolved choice, it shows a processing-ID error but does
not select, scroll to, or focus the relevant row. There is no remaining-decision
count or Next undecided action. A large cohort turns correction into a search task.

**Evidence.** `src/Main_App/gui/interpolation_burden_review_dialog.py:92-185,224-256`.
Frequency QC already has a useful Next needs attention pattern at
`src/Main_App/gui/frequency_domain_qc_dialog.py:325-330`.

**Proposed fix.** Reuse the existing attention-navigation pattern: remaining
count, **Next needs attention**, and focus on the first invalid decision when
Apply fails. Keep recording/all-visits scope visible with its choice. Do not
restructure the table merely because it has many columns; first confirm any
width problem in a visible session.

**User benefit.** Faster, less error-prone completion of large recording reviews.

**Acceptance.** Leave one decision incomplete near the bottom of a large
repeated-session list; Apply and Next must locate it and expose the correct
recording identity and scope. Counts must update as decisions are completed.

### 9. Preserve the inspected finding when filtering QC evidence — lower priority

**Problem.** Every search/type-filter change rebuilds the signal-review tree,
resets expanded groups, and selects the first result. It does this even when
the finding being inspected still matches. Clearing a temporary filter makes
users find their place again.

**Evidence.** `src/Main_App/gui/signal_review_panel.py:144-149,174-217`.

**Proposed fix.** Preserve the selected recording/episode/finding identity and
expanded groups. Restore the same selection when it remains visible; select
another result only when the current item no longer matches. Keep the current
empty-result feedback.

**User benefit.** Users can narrow and broaden evidence searches without losing
the recording they were comparing.

**Acceptance.** Select a later recording, change a matching search/type filter,
and clear it. Confirm selection, details, and meaningful expansion state remain
stable. Filtering the item out must select an appropriate visible replacement.

## Plain-language follow-up summary

- **1. Conditions:** An unfinished or duplicate row can disappear from the saved
  setup. Mark the exact problem before Save/Start so all intended conditions are kept.
- **2. Figure exports:** A new SNR figure can replace an older one. Ask only when
  names collide so users can replace it deliberately or keep both versions.
- **3. Unsaved work:** Closing or switching projects can discard edits or review
  choices. Warn only when work would actually be lost, saving repeat effort.
- **4. Repeat processing:** A file can look selected when it is no longer selected
  internally. Keep both states aligned so another run works as expected.
- **5. Disabled buttons:** Some unavailable actions give no explanation. Show
  what needs fixing beside the button so users know their next step.
- **6. Settings errors:** Popups interrupt edits before users finish typing
  related values. Use inline guidance, then enforce validation at Save.
- **7. Run results:** Outcome dialogs disappear. Keep a short outcome summary
  with output and issue links so users can return later and continue confidently.
- **8. Unfinished reviews:** Users must hunt for a recording with a missing
  decision. Add a remaining count and jump to it so reviews are easier to finish.
- **9. QC filters:** Filtering jumps back to the first finding. Keep the current
  matching finding selected so users do not lose their place.

## Preserve, defer, and verify

Preserve the current visual identity and shared component system, the anchored
Start/Stop control, focused View Log dialog, visual ROI picker, explicit QC
decisions and evidence, background workers/cancellation, beta-tool separation,
FHC result details/maps, and shared post-processing recovery. No wholesale
navigation redesign, new color scheme, extra animation, or new dashboard is
justified by this review.

Two lower-confidence/secondary ideas were not promoted into findings: reducing
no-decision QC acknowledgement pauses needs agreement about their review purpose;
adding search to FHC recording exclusions is useful mainly at larger cohort
sizes. A suspected SNR pasted-path issue was rejected because its input field
is read-only and Browse already refreshes the selectors.

Baseline review verification completed on 2026-09-18:

- `.venv1/Scripts/python.exe .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  — passed.
- `.venv1/Scripts/python.exe .agents/scripts/verify.py --scope gui --tier focused`
  — GUI audit passed; **477 tests passed**.
- Read-only, non-Qt function/helper probes confirmed condition-row loss,
  single-file selection divergence, hidden SNR validation feedback, and repeated
  export names. These establish code behavior, not a visible usability session.

At the initial review stage, no Qt application or pytest-qt session ran locally, in accordance with the repo's
local GUI execution rule. Pixel layout, display scaling, keyboard traversal and
screen-reader behavior have not been visually/runtime certified. During later
implementation, execute the acceptance scenarios above in an approved visible
session at 1280x900 and supported scaling on Windows/Linux; run registered Qt
checks in CI. None of these recommendations is claimed fixed by this review.

At that stage, only this review document was added; no runtime ownership,
structure, scientific contract, or workflow changed. The implementation record
below supersedes the initial review's verification limitations only where it
records subsequent checks explicitly.

## Implementation and verification record

The user approved all nine fixes, visible verification including clipping, and
commit/push to `codex/v3-frontend-ux-review` only. The v3 release branch must not
be merged or otherwise changed by this implementation. The implementation
preserves scientific methods, EEG marker interpretation, output data formats,
project identity, worker boundaries, ordinary sidebar navigation and the shared
PySide6 appearance. Retired packages and developer-only standalone scripts were
outside scope. No new dashboard, export-history system or scientific auto-apply
behavior was introduced.

### Implementation ledger

| Finding | Implemented behavior and source ownership | Acceptance coverage |
| --- | --- | --- |
| 1. Condition rows | `condition_input_model.py` owns whole-draft validation. `event_map.py`, `processing_inputs.py` and `project_workflows.py` reuse it for field feedback, readiness, Save and Start. Empty placeholders remain allowed; incomplete or duplicate-name rows remain visible and block committing. | `test_condition_input_model.py`; `test_main_window_event_map_enter.py` covers invalid rows, correction and exact field focus. |
| 2. SNR collisions | `Tools/Plot_Generator/export_plan.py` plans matching PNG/PDF destinations and stages publication; `export_workflow.py` checks destinations on a worker and asks Replace existing / Keep both / Cancel only for collisions. Renderers use the approved plan, retain ordinary names/folders, and protect against changed destinations. | `test_export_plan.py` covers pairing, suffixes, cancellation, replacement and failed publication; `test_plot_generator_gui.py` covers the real collision prompt and launch handoff. |
| 3. Unsaved work | `project_drafts.py` and `settings_feedback.py` track setup edits and protect project replacement/exit. Failed or still-running saves cannot authorize leaving. `components/review_dialog.py` protects changed frequency, kurtosis and burden review choices with Keep reviewing / Discard choices; unchanged reviews close directly. | Main-window and Settings tests cover Save/Discard/Cancel and failed-save paths. `test_interpolation_burden_review_qt.py` exercises real Cancel/Escape/X prompts, safe default, preserved choices and single-prompt close. Frequency/kurtosis tests cover their decision snapshots. |
| 4. Single-file selection | `processing_inputs.py` uses the displayed BDF selection for readiness and launch. `processing_completion.py` retains that selection in single mode and refreshes readiness. | `test_main_window_event_map_enter.py` covers completion followed by another valid selection check and removal of the underlying BDF. |
| 5. Disabled actions | `Plot_Generator/gui.py` and its UI helpers expose actionable readiness text; `Free_Harmonic_Clustering/gui/page.py` exposes setup errors and a control-focus action. Main processing uses the same condition-validation result beside Start. Idle valid-state messages do not consume unnecessary space. | SNR and FHC Qt tests cover invalid comparisons, visible reasons, focus actions and clearing feedback after correction. |
| 6. Settings feedback | `settings_feedback.py` presents non-modal field feedback and tracks value changes; `settings_panel.py` permits intermediate edits and tab changes, then validates and focuses the exact field at Save. `roi_settings_editor.py` distinguishes changed ROI content from selection-only navigation. | `test_frontend_settings_qt.py` covers invalid drafts, keyboard/tab navigation, save failure/success, asynchronous-save boundaries, partial recalculation and bounded tab/action layout. |
| 7. Last-run outcome | `run_outcome_model.py` summarizes established recording outcomes; `run_outcome.py` presents a session-local summary with output/issues links. `processing_workflows.py` and `processing_completion.py` integrate completion, cancellation and post-processing readiness; project/run changes clear stale context. | `test_run_outcome_model.py` covers outcome counts/states; main-window Qt coverage checks compact geometry and existing output/issue actions. |
| 8. Burden attention | `interpolation_burden_review_dialog.py` adds ready/remaining counts, Next needs attention and first-unfinished-row focus/scroll on Apply. The existing table and scopes remain; the visually clipped session header was shortened to Session / phase with the full wording in its tooltip. | A 60-recording fixture checks a late unresolved row, wraparound navigation, completion counts and unchanged Apply authority. Visible checks cover 1180x650 and 1280x900. |
| 9. QC filter context | `signal_review_panel.py` retains a still-matching selected finding and recording/episode expansion across search/type changes. An item filtered out yields a visible replacement; empty-result feedback remains. | `test_signal_review_panel_qt.py` covers matching selection, restored filters, expanded groups, evidence identity and empty results. |

Source names without a tool prefix are under `src/Main_App/gui/`. GUI test
names are under `tests/gui/`; SNR tests are under `tests/plot_generator/`.
Ownership and visible smoke paths are recorded in
[GUI architecture](../architecture/gui.md) and the scoped SNR/FHC `AGENTS.md`
files. The temporary execution plan's scope, ownership and acceptance are
retained here; its completed active-plan file was removed under the execution
plan retention policy.

### Verification ledger

- QC widget-free regressions: **172 passed** across the two focused runs.
- QC visible Windows interaction suite: **64 passed**. Real message boxes were
  explicitly restored in prompt tests because the general test harness normally
  suppresses them. Existing stale fixtures were aligned with canonical recording
  IDs, current interpolation labels, explicit repair confirmation and native Qt
  checkbox/tuple-selection behavior.
- QC final themed capture matrix: **9 passed at each of 100%, 125% and 150%**
  (`27` final checks). Representative dense frequency review, burden error and
  navigation, filtered/restored signal evidence, and the discard confirmation
  were inspected. The 100% capture was refreshed after the session-header fix.
- Tool interaction suite: **48 passed** in `build/fux-tools-results3.txt`;
  the subsequent folder-button layout check passed **14 tests** in
  `build/fux-tools-results4.txt`. Export safety coverage passed **16 tests**,
  including case-only condition/ROI names on Windows.
  Tool capture checks recorded in `build/fux-tools-{100,125,150}.txt`:
  **6 passed per scale**, with 29 other tests deselected in each focused run.
- Settings and main-workflow final suite: **76 passed** in
  `build/fux-main-complete.txt`. The capture matrix passed **19 checks per scale**
  plus the real Save/Discard/Cancel prompt at each scale. The final 150% capture
  refresh passed all **20 checks** together in `build/fux-last-scale.txt`.
  Screenshots are in `build/frontend-ux-screens/{100,125,150}/` and
  `build/frontend-ux-tools-{100,125,150}/`.
- Visible inspection also corrected the Settings minimum width, condition-row
  error spacing, the Settings information icon and the SNR folder-button width.
- Repository precommit gate: **5,004 passed, 11 skipped**, exit code 0;
  all audits, Ruff and compilation passed. Recorded in
  `build/fux-precommit-final.txt`. The run used `--basetemp=C:/fuxg` because
  deeply nested Windows fixture paths exceeded the legacy path limit in the
  first run. The two outdated protocol-input test doubles were updated to use
  the shared validator; the scientific assertions were retained. Existing
  conditional skips include Windows symlink privilege checks; the run also
  reported 67 dependency/numerical warnings, with no failures.
- The three visible interaction suites passed **188 tests** in total; the
  focused layout/prompt matrix additionally passed **35 checks per scale**
  (20 Settings/main, 9 QC, 6 tool checks). Inspected changed surfaces have no
  observed clipped controls or actions at the exercised sizes and scales.
- Focused QC Ruff, GUI import audit and diff whitespace checks passed. Final
  integrated checks supersede these narrower results when recorded above.

The local capture artifacts are ignored build output, not release assets:
`build/frontend-ux-qc-{100,125,150}/` contains PNGs; matching `.txt` and `.xml`
files record the runs. The broader QC result is `build/fux-qc-results.txt` with
`build/fux-qc4.xml`. Optional captures use `FPVS_UX_SCREENSHOT_DIR`; the QC
capture fixture applies the actual FPVS theme and restores the prior application
appearance after each test.

### Reproduce the checks

Run the applicable local gates with the repository environment:

```powershell
.venv1/Scripts/python.exe .agents/scripts/verify.py --scope gui --tier focused
.venv1/Scripts/python.exe .agents/scripts/verify.py --scope plot-generator --tier focused
.venv1/Scripts/python.exe .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
$env:PYTEST_ADDOPTS = '--basetemp=C:/fuxg'
.venv1/Scripts/python.exe .agents/scripts/verify.py --scope repo --tier precommit
Remove-Item Env:PYTEST_ADDOPTS
```

The user approved a safe visible Windows session for this task. Run Qt processes
sequentially, using the native Windows platform; never substitute offscreen.
The following repeats the final nine QC capture checks at each tested scale:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$qcNodes = @(
  'tests/gui/test_frequency_domain_qc_dialog_qt.py::test_compact_review_fits_without_horizontal_table_scrolling'
  'tests/gui/test_interpolation_burden_review_qt.py::test_missing_decision_focuses_and_scrolls_to_unfinished_recording'
  'tests/gui/test_interpolation_burden_review_qt.py::test_attention_controls_fit_dialog'
  'tests/gui/test_interpolation_burden_review_qt.py::test_dirty_exit_can_keep_reviewing_or_explicitly_discard[close]'
  'tests/gui/test_signal_review_panel_qt.py::test_filter_keeps_matching_selection_and_expanded_recordings'
)
foreach ($captureScale in @('1', '1.25', '1.5')) {
  $captureLabel = @{ '1' = '100'; '1.25' = '125'; '1.5' = '150' }[$captureScale]
  $env:QT_SCALE_FACTOR = $captureScale
  $env:FPVS_UX_SCREENSHOT_DIR = Join-Path (Get-Location) "build/frontend-ux-qc-$captureLabel"
  .venv1/Scripts/python.exe -m pytest @qcNodes --allow-qt-tests "--basetemp=C:/Temp/fux-qc-$captureLabel" "--junitxml=build/frontend-ux-qc-$captureLabel.xml" -q
  if ($LASTEXITCODE -ne 0) { throw "QC visible checks failed at $captureLabel percent" }
}
Remove-Item Env:FPVS_UX_SCREENSHOT_DIR
Remove-Item Env:QT_SCALE_FACTOR
Remove-Item Env:QT_QPA_PLATFORM
```

For the full changed-surface interaction set, run these registered files in a
separate approved visible process with `--allow-qt-tests` and a short temporary
directory: `tests/gui/test_frontend_settings_qt.py`,
`tests/gui/test_main_window_event_map_enter.py`,
`tests/gui/test_frequency_domain_qc_dialog_qt.py`,
`tests/gui/test_kurtosis_review_actions_qt.py`,
`tests/gui/test_interpolation_burden_review_qt.py`,
`tests/gui/test_signal_review_panel_qt.py`,
`tests/plot_generator/test_plot_generator_gui.py`,
`tests/plot_generator/test_plot_generator_gui_refactor_smoke.py`, and
`tests/gui/test_free_harmonic_clustering_page.py`.

### Verification boundaries and handoff

Visible checks used synthetic Windows fixtures, native Qt, real FPVS styling,
logical workspaces no larger than 1280x900, and 100%/125%/150% scale factors.
They verify the exercised labels, actions, focus, interaction and geometry;
they are not a real-EEG processing run, numerical revalidation, Linux visual
certification, screen-reader audit or exhaustive inspection of every beta tool.
Deliberately elided table identities retain full evidence/tooltip access and
content-native scrolling remains supported. Scientific decisions still require
the established explicit validation and Apply/save paths.

The complete diff was reviewed against the nine findings. Commit/push target:
`codex/v3-frontend-ux-review` only; the task handoff records the final commit and
remote verification. No merge into `codex/v3-release` is part of this work.
