# FPVS Toolbox v3.0.0 Release Readiness

## Status

Active. This is the release ledger for the first v3 release candidate.

Menu-visibility follow-up on 2026-10-11: the retained platform menu palette now
sets matching painted backgrounds and text on menu bars, popup menus and their
items, with matching selected/pressed and disabled colors. This addresses the
Windows native painter using light backgrounds with the previously retained
white text. Menu actions, routing and page visibility rules are unchanged.
Qt-free coverage checks light/dark color pairs; CI rendering coverage models
the mismatched native painter and checks normal, pressed, disabled and popup
labels at standard and 1.25/1.5/2 scaling. Settings/Home/Welcome visibility is
also covered. The native Windows manual path is in
[`gui.md`](../../architecture/gui.md); Qt was not executed locally.

Verification: the new Qt-free color-pair regression failed before the fix and
passes for both light and dark palettes afterward. GUI focused passed 602
tests. Repo precommit passed all audits, Ruff, compilation and 5,790 non-Qt
tests (two skipped; 73 existing warnings), using `C:/fmenu1011a`. Strict docs,
CI workflow YAML parsing and `git diff --check` passed. Native Windows visual
confirmation remains outstanding; the CI render/scale tests were not run
locally.

Harmonic-help follow-up on 2026-10-11: Settings > Harmonics uses descriptive
method names and a shared information modal for the currently selected method.
Each page gives a brief explanation and its own publication links: seven for
the two-failure rule, six fixed-domain examples and three significant-selection
examples. The 2020-onward search plus foundational papers is a verified
collection rather than a systematic census. Method variants and the lack of
a publication for Legacy's exact isolated-peak guard are stated explicitly.
Source evidence and exclusions are recorded in the
[methods checklist](../../../user/reference/methods-reporting-checklist.md#harmonic-method-references).
The profile IDs, versions, persistence and numerical selection are unchanged;
no ownership or backend architecture change was needed.

Verification: GUI focused passed 600 non-Qt tests; strict documentation build
passed. A Qt-free catalog check parsed all four help pages and verified that
all 16 distinct DOI links match the source-review documentation.
`test_harmonic_method_help_opens_current_profile_without_changing_drafts`
checks current-selection routing, links, resizing, closing and preservation of
project/draft settings in CI, including the existing 1.25/1.5/2 scale-factor
matrix. Native Windows checks at 1080p/100%, 4K/150% and
the supported minimum workspace remain on the documented visible/manual path;
Qt was not executed locally. Full repo precommit passed all audits, Ruff,
compilation and 5,788 non-Qt tests (two skipped; 73 existing warnings), using
`C:/fhinfo1011a`. CI workflow YAML parsing and `git diff --check` also passed.

Protocol-layout follow-up on 2026-10-11: Settings > Protocol now separates
Timing from Trigger markers. The condition table receives expandable vertical
space outside the timing form; recording controls, status and Save/Cancel stay
separate. The shared status remains visible on either page, and invalid inputs
reveal the correct page. Existing project values and save/cancel behavior are
unchanged. Geometry coverage uses fixed logical workspaces for the supported
minimum, 1080p at 100%, 1440p at 125% and 4K at 150%; CI repeats it at scale
factors 1.25, 1.5 and 2. Native Windows scaling and monitor-switching checks
remain on the visible/manual path in [`gui.md`](../../architecture/gui.md).

Verification: the GUI focused gate passed 600 tests. Repo precommit passed all
audits, Ruff, compilation and 5,788 non-Qt tests (two skipped; 73 existing
warnings) using `C:/fpl1011a`. The strict documentation build passed. The new
`test_protocol_sections_fit_scaled_workspaces_with_marker_tables` geometry
coverage and scale-factor runs are configured for CI; no local Qt execution
or native Windows display verification ran.

Experimental-QC follow-up on 2026-10-11: Settings > Experimental now separates
Preprocessing QC from Post-processing QC, with brief feature information and
dependent repair controls grouped under their parent screen. New projects
persist optional QC off; existing projects retain their previous choices,
including the former SNR-tool preference. Independent switches control raw
signal review, removed-electrode detection, kurtosis, raw-spectral review,
interpolation-burden review, summed-BCA review, SNR peaks and Stats finite-value
flags. Trigger plans, nonfinite/corrupt results, FFT grids, canonical harmonic
identity and complete ROI/output coverage remain mandatory.

Disabled checks produce no optional findings and report disabled evidence
accurately. Post-processing switches preserve accepted exclusions and
condition-specific repairs. Per-recording preprocessing
screen snapshots prevent Resume Post-processing and analysis from reusing
outputs made under different screening choices. The settings pages, schema
migration, runtime combinations and mandatory gates have focused regression
coverage. Visible/manual acceptance remains documented in
[`gui.md`](../../architecture/gui.md); registered Qt coverage remains CI-only.

Verification: the final repository precommit gate passed all audits, Ruff,
compilation and 5,786 tests (two skipped; 73 existing warnings), using a fresh
short fixture root (`C:/fqc1011c`). The strict documentation build passed.
Focused coverage includes all 128 combinations of the seven optional screen
settings, independent raw-signal/detector behavior, disabled-screen integrity,
resume/cancel behavior, legacy migration and per-recording stale-output gates.
No local Qt workflow or installer build ran.

Tool inventory follow-up on 2026-10-09: the sidebar and Tools menu now share
exactly six beta surfaces through `Main_App.gui.sidebar.BETA_TOOL_SPECS`.
Runtime, icon, test, verification, and documentation inventories agree.
Project data, existing generated results, processing, and statistical methods
retain their existing behavior.

Verification: the focused GUI gate passed 598 tests; the repository audit
bundle passed 25. The broad non-Qt precommit gate passed all audits, Ruff,
compilation, and 5,395 tests with 24 skips using a fresh short non-temp fixture
root. The strict documentation build passed. Registered GUI coverage remains
CI-only. Visible smoke: toggle Beta Tools and restart, verify the sidebar and
Tools menu contain the same supported inventory, and open the remaining tools.
No local Qt workflow ran and no installer was rebuilt.

Priority-bug follow-up on 2026-10-09: condition names that collapse to the same
case-insensitive output name after numeric-prefix stripping now fail draft
validation, expected-plan creation, processing planning, direct worker startup,
and export before results can be overwritten. Valid folder names, filenames,
processing order, and scientific calculations retain their existing behavior;
the shared naming owner is `Main_App.projects.grouping`.

The main-window close path now refuses active processing, pending finalization,
queued/active post-processing, and owned background-thread cleanup without a
blocking wait. Sequence Figure exposes its page-owned export lifecycle to both
close and update-install guards. Its cached page refreshes project/output
context on open while retaining manual inputs and immutable running-export
specifications; a project-context version prevents old results reattaching even
after an A-to-B-to-A switch. Focused GUI/updater architecture and tool-local
instructions record the visible smoke paths; local Qt execution remains unrun.

Verification: focused gates passed processing (2,125 tests; six skips), GUI
(597), project I/O (431; 12 skips), updates (435; four skips), and Sequence
Figure (36). Repo precommit passed all audits, Ruff, and compilation, then
reported 5,400 passes, 24 skips, and eight fixture-location failures: four FHC
exports exceeded Windows path limits and four LORETA fixtures were rejected
under the system temp directory by the existing cache-location policy. All
eight exact failed nodes passed with a fresh short non-temp absolute
`--basetemp=C:/f418e` (eight passes). FHC/LORETA code and tests were unchanged.
The strict documentation build passed. Registered Qt execution and the visible
smoke paths remain CI/manual verification; no installer was rebuilt.

Private-source migration on 2026-10-07: `zcm58/FPVS-Toolbox-Repo` is private,
with all original remote refs preserved. Public distribution now lives in
`zcm58/FPVS-Toolbox-Releases`, whose independent main branch and release tags
contain only its README. All 28 historical installer assets were copied with
size/SHA-256 verification; the latest public installer remains 2.1.2. Anonymous
repository/release/raw-source requests to the source repository return 404,
while the release repository remains publicly accessible. No 3.0.0 installer
was built or published. The user chose to defer that release and accepted the
one-time manual upgrade from older installers when 3.0.0 becomes available.

The 3.0.0 main application and independent updater share the public release
identity, retaining exact URL/version/filename and SHA-256 checks without
client credentials. The focused updates gate passed 433 tests with four skips.
A live, unauthenticated backend probe selected/downloaded public 2.1.2 and
matched its original 141,503,904-byte installer digest; 3.0.0 correctly received
no downgrade offer. No installer or GUI was executed. Public documentation is
intentionally unpublished at the user's request; the docs workflow now only
validates, and the strict documentation build passed.

The repo precommit gate passed its audits, Ruff and compilation, then reported
5,371 passes, 24 skips and five existing FHC export failures under the deep
repository `test_tmp` path. All five exact failed nodes passed with a fresh
short absolute `--basetemp` (`C:\fpa11d66`); no FHC code or tests changed. The
failures were in exploratory exports, the planned-family integration export,
and repeated-session batch export/cancellation. Local Qt execution and a
rebuilt-installer/manual-upgrade smoke remain deferred to the 3.0.0 release.

RAM-setting location follow-up on 2026-10-06: the existing toggle now lives in
Settings > Experimental > Performance, with the same project-only value,
default-off state and shared Save/Cancel draft handling. Preprocessing no longer
contains the toggle. Registered Qt coverage checks the five Experimental pages,
RAM parentage and project/projectless state, Cancel, Save and reopening. The
visible 1280x900 keyboard and persistence smoke route is recorded in `gui.md`;
local Qt execution remains unrun under the GUI skill's explicit-approval rule.
Verification: the GUI focused gate passed 586 tests. The repo precommit gate
passed all audits, Ruff and compilation, then 5,395 tests (two skipped; 73
existing warnings).

Menu follow-up on 2026-10-06: Toolbox now follows Studio's File/View/Tools
organization. File separates project actions, settings/cache maintenance,
updates/About, and Exit. View returns to Home; Tools reuses the sidebar's
default and optional beta registrations and shared beta acknowledgements.
The existing theme owner retains a separately owned native menu style and
explicit startup palette before applying the Toolbox light theme. Local
foreground-only menu rules preserve native geometry and selection backgrounds
with the shared 13px text size. Existing callbacks, action aliases, Welcome
visibility and processing/cache-reset menu locks remain intact.

The GUI focused gate passed all audits, Ruff and compilation, then 586 tests.
The repo precommit gate passed all audits, Ruff and compilation, then 5,395
tests (two skipped; 73 existing warnings). Pure checks cover native-style
ownership, palette retention through repeated
theme changes and explicit style-creation failure. Registered Qt smoke coverage
checks menu grouping, Home, tool visibility/routing and shared beta warnings.
Qt execution and installer rebuilding were not performed; the visible
1280x900 long-label, keyboard and action checks are documented in
`docs/agent/architecture/gui.md`. The captured palette does not refresh during
live OS theme changes; Toolbox retains its shared font family.

RAM-preload follow-up on 2026-10-06: the project-only, default-off Experimental
RAM preload switch in Settings > Experimental > Performance passes through ordinary
processing, preflight QC, kurtosis scanning and source prefetch. Disk loading
remains the default. RAM prefetch creates no staging directory, caps retained
buffers at 25% of available memory, and keeps the existing exclusive handoff,
source validation and cleanup rules. Scientific processing fingerprints and
preprocessed-Raw cache keys exclude this storage choice. Review fixed a missing
flag in the compatibility controller's local parameter snapshot. The associated
single-session export receipt fix prefers the registered participant ID over a
raw filename alias; explicit repeated-session recording IDs retain precedence.

Implementation uses the existing `Main_App/Shared/load_utils.py`,
`Shared/post_process.py`, `Performance/process_runner.py`,
`gui/processing_inputs.py`, `gui/settings_panel.py`,
`projects/preprocessing_settings.py` and `processing/` owners
`preflight_qc.py`, `kurtosis_review_scan.py`, `qc_source_prefetch.py`,
`processing_controller.py` and `processing_ledger.py`. Existing focused tests
cover loading, flag propagation, exact preprocessing equality, cache identity,
receipts and cleanup. Protected-path audits leave retired `Legacy_App` and
`PySide6_App` paths untouched. Project-local prefetch paths continue to use the
active `Project.project_root`; no hard-coded acquisition paths were added.

The developer diagnostic `scripts/manual_diagnostics/benchmark_bdf_preload.py`
creates only synthetic BDFs in its temporary directory. Four workers with four
60-second recordings produced identical SHA-256 values after real preprocessing
in disk and RAM modes. This small correctness probe is not a representative
production speed estimate. GUI execution and installer rebuilding were not
performed. The visible 1280x900 Save/Cancel/cache-miss smoke route is documented
in `docs/agent/architecture/eeg-loading-contract.md`.

Verification: the final `verify.py --scope repo --tier precommit` gate passed
all audits, Ruff and compilation, then 5,393 tests (two skipped; 73 existing
warnings). The focused RAM-loading/cache/receipt/settings bundle passed
366 tests; two additional compatibility-controller cases passed. The synthetic
probe used `benchmark_bdf_preload.py --seconds 60 --rounds 1`. Its buffers and
recordings were temporary; no real research data was read or changed.

Settings organization follow-up on 2026-09-25: seven purpose-based tabs now
separate Quality Control, Experimental, and Application controls. Stats alpha
is under Application > Analysis Defaults; Beta Tools is under Experimental.
One shared Save/Cancel footer covers all pages. Experimental > Electrodes now
exposes the persisted default-On >10 kurtosis-review checkbox preference for
new decisions, preserving per-review overrides, Apply decisions, accepted
receipts, numerical methods, and processing fingerprints. Current navigation
and method docs plus the GUI manual-smoke route are updated. The user approved
visible local Qt verification on 2026-09-25. Screenshot review identified and
resolved a nine-pixel dialog-height overflow by combining the ROI scope note
with the montage label; balanced form columns also reduce label wrapping.

Verification: `verify.py --scope gui --tier focused` passed 564 tests and
`--scope project-io --tier focused` passed 338. The targeted experimental
settings, kurtosis-review and processing-fingerprint bundle passed 195 tests.
The repo precommit gate passed all audits, Ruff and compilation, then reported
5,209 passes, 11 skips and five FHC export failures caused by Windows temporary
path lengths. All five failed tests passed when rerun with a fresh short
`--basetemp`; FHC source and test files were unchanged. Registered Qt coverage
now checks tab/control placement, shared actions, Save/Cancel, projectless beta
availability and the review default. All 28 approved visible Qt checks passed
on Windows, including seven main tabs, four Experimental sections, project
round-trip, beta restart prompting, per-review overrides, Enter to save and
Escape to cancel. Final screenshots showed no clipping or overlap at the
tested dialog and 1280x900 embedded workspace sizes. Evidence is in
`%TEMP%/fpvs-settings-visual-20260925`; Linux and other display scaling settings
were not exercised. Test preferences are isolated from legacy machine settings.

FHC Results density on 2026-09-21: the Results card/table now use the available
tab height instead of leaving it to a blank spacer. Font-aware single-line
rows avoid hidden-tab wrapping that previously inflated rows to roughly
100 pixels. The view filter and details/maps actions sit above the table;
family Holm p-values align right, and full labels remain in tooltips/details.
Shared typography, result identities, filtering, statistics, exports, and map
membership are unchanged. The existing CI Qt page suite now defines a
ten-comparison geometry regression across 1280x800 and 1280x900 page sizes.
The tool's architecture document records the visible smoke path, including
long labels, resizing, filtering, and empty results. Qt was not run locally.

FHC verification: `--scope free-harmonic-clustering --tier focused` passed
317 tests and `--scope gui --tier focused` passed 562 tests. The final
`--scope repo --tier precommit` run passed all audits, Ruff, and compilation;
pytest reported 5,174 passed, 11 skipped, and one failure in the unchanged
preflight-cache concurrent-writer test when Windows denied `os.replace`
with `WinError 5`. An elevated rerun of
`python -m pytest -q tests/processing/test_preflight_qc_cache.py` passed all
16 tests. That test bypasses GUI wiring and writes only to its own temporary
project root; the file-access failure did not reproduce, and no unrelated
cache change was made. The new Qt geometry test is compiled but awaits CI
execution; the visible smoke path remains pending.

Kurtosis checkpoint handoff on 2026-09-21: the GUI binds the active
`Project.project_root` in the kurtosis worker's settings copy. Previously
only the final runner supplied it, so review silently disabled prepared-cache
publication and final processing repeated the reference/filter/downsample/
scoring prefix. The existing exact float64 checkpoint now bridges those paths;
source validation and current decision authority still run before interpolation
and final reference. The shared settings and existing processing-ledger
fingerprints stay unchanged. The review page explains this continuation. No
scientific method, processing order, output format, or retired package changed. Headless
regressions cover switching active projects and real scanner-to-preprocessing
reuse from GUI-built settings, with exact sample/evidence/receipt equality and
guards against repeated filtering, resampling, and kurtosis. A separate real
BDF-loader probe confirmed reuse across independent memmap loads. The visible
1280x900 review/cancel/settings-change smoke path is recorded in the
preprocessing contract; local Qt execution remains disabled.

Verification: the final `--scope repo --tier precommit` gate passed 5,175 tests
with 11 skips and 69 warnings; all agent audits, Ruff, and compilation passed.
The new handoff regression also fails under an in-memory restoration of the
original missing-root wiring. The initial sandboxed processing gate encountered
Windows worker-pipe and temporary-directory permission failures; those same
tests passed in the final gate outside the sandbox. No user recordings or
project settings were changed during verification.

Native-result completion follow-up on 2026-09-10: Semantic Categories completed
processing successfully, but the GUI's remaining Excel-only output snapshots
left `_last_job_success` false and replaced the completion message with
"No Excel files were generated." A read-only public dataset-index and companion
validation found all 135 current-run native condition results present and valid,
including their spectral and metric arrays/checksums. The active cohort contains
130 results with one existing manual frequency-QC exclusion;
all five excluded result files also remain present. Final release readiness passed.
This is a completion-detection/copy fix, not a data recovery or reprocessing task.
No project data, settings, exclusions or scientific methods were changed.
The GUI and post-export worker now use `Main_App.io.result_outputs` for native
and historical result anchors, with compatible wrapper/payload names. Both
success and missing-output messages say result files. The helper detects all
135 actual project results; 22 new headless tests cover native/legacy writes,
overwrites, unchanged prior outputs, orphan companions, error paths and worker
payloads. Focused GUI and project-I/O gates passed 534 and 312 tests; the focused
post-export bundle passed 37. The native completion/empty-output smoke path is
recorded in `.agents/verification.toml`; Qt execution remains CI-only locally.
The final repo precommit gate passed 4,617 tests with seven skips and 67
warnings. Agent audits, Ruff, compilation and diff checks passed; existing
CI-only popup tests now include native results. The first GUI gate encountered
the new-test registry guard; registering the headless test file resolved it
before the successful focused and final runs.

Recording marker support on 2026-09-10 supersedes the condition-only cohort
configuration described below. A read-only audit of all 27 registered Semantic
Categories BDF Status channels found mixed acquisition schemas. One cohort uses
condition codes 1..5 -> oddball codes 51..55; another cohort uses shared
code 55. The new opt-in protocol v1.3 saves complete, explicit mappings for each
canonical recording. Unassigned recordings fail with a Settings remedy;
neither filenames nor event counts select a schema automatically. Existing
v1.1/v1.2 canonical payloads and fingerprints remain unchanged. All recordings
share the same full-project protocol fingerprint, while approved marker plans
and cached source spans bind the canonical recording identity as well.

The Protocol page opens a focused recording schema dialog using public project
registry identities. New rows require assignment, custom saved values survive
template edits, selected-row bulk assignment is explicit, and cancelling keeps
changes out of saved Settings. Missing marker evidence no longer claims the
recording itself is too short. Implementation extends the existing protocol
and processing owners plus `gui/recording_marker_schemas.py` and
`gui/recording_marker_schemas_dialog.py`; no processing order, cycle count,
trigger onset boundary, exclusion policy, or raw/processed data changes.

The corrected protocol was exercised through the actual marker planner for
all 27 BDFs: all 259 detected occurrences had 147 configured markers and passed
marker timing without review. Uneven onset repetitions remain faithfully
represented, including recordings with five blocks, nine blocks, and unequal
counts across conditions. They were not repaired by guessing additional events.
After verifying the Toolbox process had closed, all 27 explicit assignments
were saved to the Semantic Categories manifest. Only `frequency_protocol`
changed; an exact backup was saved beside it as
`project.json.before-recording-markers-20260910-171536-201659.bak`. The saved
protocol was reloaded and matched the protocol used for the full cohort audit.
Focused project-I/O and
GUI gates passed 312 and 512 tests respectively; processing passed 2,027 tests
with five skips and 59 warnings. Qt execution remains CI-only;
the visible schema assignment/QC smoke path is in `.agents/verification.toml`.
The final repo precommit gate passed 4,595 tests with seven skips and 67
warnings; all agent audits, Ruff, compilation and diff checks passed. Qt
interaction was not executed locally, and developer-only standalone tests
remained outside this task's verification scope.

Condition marker support on 2026-09-10: an explicit project-only Protocol
switch maps each canonical condition onset to its oddball marker. Mapped
projects use protocol v1.2; existing shared-code v1.1 payloads and fingerprints
remain unchanged. Full mapping coverage and onset/oddball disjointness are
required. QC planning, reviewed-span validation, runner epoch/source metadata,
post-processing cropping and expected-ledger checks resolve the same code.
The mapping fingerprints prior decisions and outputs stale; it changes no
expected cycle count, duration, preprocessing order, or crop alignment rule.
After the user closed the Toolbox, Semantic Categories was explicitly configured
for onset codes 1..5 -> oddball codes 51..55. Only its protocol JSON value was
changed, with an exact original-manifest backup next to project.json; its
144-cycle/120-second setting was preserved. No raw or processed data was changed.
The protocol/public export owners are `Main_App/projects/frequency_protocol.py`
and `projects/__init__.py`; GUI adapters are `gui/project_protocol.py` and
`gui/settings_panel.py`; processing changes are in `processing/marker_integrity.py`,
`Performance/process_runner.py`, `Shared/post_process.py`, and
`processing/expected_processing_ledger.py`. No retired paths or global trigger
defaults changed.

Verification: the project-I/O focused gate passed 293 tests; the final GUI gate
passed 502 locally safe tests including the alias regression. The final adapter/static
bundle passed 22 tests, including a single editable row for condition aliases
sharing an onset. The processing gate had 2,006 passes and five skips plus one
Windows temporary-file PermissionError in an unchanged test; its immediate rerun
passed. The repo precommit gate then passed 4,549 tests with seven skips and 67
warnings. Agent audits, Ruff, compilation and diff checks passed. A read-only
Status-channel inspection of registered study-participant confirmed two repetitions per
condition, each with 147 markers of its assigned code and none of the other
51..55 codes: the former shared-55 rule missed eight of ten blocks. No EEG
preprocessing or local Qt execution was run; two GUI tests remain CI-only, and
the visible Protocol/QC smoke path is recorded in `.agents/verification.toml`.

FHC loading recovery on 2026-09-10: missing or incomplete project protocols now
show the specific reason and an Open Protocol Settings action, without leaving
the family card in a loading state. Returning after protocol confirmation loads
the same page; failed/cancelled inspections offer retry after worker exit and
hide stale family choices. Old export rates do not bypass protocol confirmation
or neutral FullFFT provenance validation. Raw discovery and repeated-source
preflight retain canonical IDs for exact registered raw paths, so historical
participant IDs survive changes in filename inference; source/group conflicts,
duplicate ownership and new-file confirmation remain checked. No user project
manifest or source data was edited. The FHC focused gate passes 315 tests,
the GUI gate passes 480 locally safe tests, and project-I/O passes 253 tests;
eight headless loading-state regressions and
CI-only GUI recovery cases cover the reported workflow. The visible smoke path
includes protocol repair, cancelled/failed loading, retry and stale-state reset.
Final repo precommit passed 4,514 tests with seven skips and 67 warnings after
updating the existing static assertion to recognize the shared protocol
validator. The focused recovery/routing bundle passed 68 tests. Agent audits,
Ruff, compilation and diff whitespace checks passed. Developer-only standalone
tests were excluded under their opt-in boundary; no local Qt run was performed.

FHC analysis-family update on 2026-09-10: new GUI runs use the explicitly
requested `fhc_analysis_families_v2` contract. Setup freezes between-group,
optional paired-condition, within-group visit, and group-difference-in-visit-
change comparisons. Both groups' visit changes share one Holm family; the
two-group/two-visit/four-condition default is 4/8/4 comparisons. Single-group
and additional-group designs use the same paired/independent engines. Exact
comparison identity and seeds are separate from correction membership.
Legacy v1 APIs and result bundles retain their original behavior. New outputs
save the immutable plan, fingerprint, family results, descriptive cluster maps,
and actual per-comparison participant identities beneath the project's FHC
results directory. No Stats tool or standard harmonic-profile code changed.

The FHC focused gate passed 308 tests; the GUI-focused gate passed 472 locally
safe tests. Additional independent integration coverage runs all four families
through real preparation/inference/export on synthetic inputs, with figure
rendering stubbed. This is software regression coverage, not calibration of
the new scientific extension. Qt execution remains CI-only; the updated
`.agents/verification.toml` smoke path covers Setup/Results/maps at 1280x900,
4/8/4 family counts, reference/all-pairs choices, persistent independent plan
and exclusion preferences, cancellation, and original map indices after
filtering. Review comparisons shows planned directions/counts; eligible Ns
are resolved during preparation and reported after completion.
The repository precommit gate passed 4,493 tests with seven skips; the
developer-only standalone-script tests were excluded under their opt-in
boundary. A final export/reporting regression bundle passed 18 tests after
the presentation was checked to depend on comparison semantics independently
of its correction-family label. Agent audits, Ruff, compilation and diff
whitespace checks passed. No local Qt run or new powered calibration was run.

Linux settings-path recovery on 2026-08-30: ported `185d803f` with Windows
override and `%LOCALAPPDATA%` behavior explicitly preserved. Invalid relative
XDG config roots now use the stable home fallback on non-Windows systems.
The widget-free platform matrix passes 15 tests; the registered project-I/O
bundle passes 116 tests. The path audit is separately blocked by eight existing
machine-path findings in untracked local `outputs/`, which remain untouched.

Sequence Figure recovery on 2026-08-30: independently ported the features from
`f13c4334` and `49434bd9`: one to four conditions (default three), two oddball
cycles per row, bounded custom labels, grayscale-safe markers, and optional
PDF-only transparency. The current shared information and output-folder actions
remain in use. Condition tabs replace the old branch's wide picker grid to fit
the supported embedded workspace; long condition labels wrap without reducing
publication font size. Existing output locations, PNG/PDF/SVG formats, 600-DPI
defaults, and manual-image-only inputs remain unchanged. The tool's scoped
`AGENTS.md`, user guide, and verification smoke path document the expanded UI.
The renderer/helper/figure-style bundle passes 31 tests; the GUI focused gate,
changed-file Ruff, compilation, and verification configuration checks pass.
Synthetic three- and four-condition PNG exports were visually checked, including
grayscale markers and maximum-length labels. The new
`tests/sequence_figure/test_sequence_figure_gui_qt.py` covers condition tabs,
bounded layout, retained hidden selections, picker cancellation, and export
payloads, but remains CI-only; no local Qt session was run. The project-I/O,
figures, Sequence Figure, and repo-precommit drivers stop at the same eight
pre-existing `outputs/` path findings above, so those full gates are not green.

FHC closeout progress on 2026-08-16: the five calibration-bound source files
are Git-identical to the reviewed calibration commit, the method/protocol/
adjacency identities and Python/NumPy/SciPy versions still match the receipt,
and exact XLSX ingestion now comes from neutral `Main_App.io` rather than the
beta Stats package. FHC and the neutral Main App processing paths it invokes no
longer import the Stats XLSX adapter. The behavior-preserving reader relocation
passed the FHC focused gate with 118 tests, including the exact shared-reader
suite; the Stats compatibility adapter has its own focused test. The closeout
branch also passed project-I/O (83 tests), Stats (384 tests), processing (357
tests and one skip), and repo precommit (1,621 tests and three skips) gates.
The remaining FHC gates are the registered CI-only embedded-page smoke and one
compact session from the final packaged Windows RC. That session must include
the canonical ACR reproduction plus the ordinary cancellation/output checks
below; it is not another powered calibration.

SNR grid-safety progress on 2026-08-16: two-condition overlays now require the
same ordered physical FullSNR grid already required within each condition. A
mismatch is reported before aggregation or rendering, and matching/mismatching
worker regressions protect the contract without adding GUI or resampling logic.
The Plot Generator focused gate was expanded to include the previously omitted
locally safe rendering and QC modules.

SNR release-closeout progress on 2026-08-16: cancellation is now cooperative;
managed runs consume frozen processing provenance and the exact active workbook
family; multi-group projects cannot fall through to an implicitly pooled curve;
and each completed figure is written as a matching PNG/PDF pair directly into
the selected `2 - SNR Plots` folder. The figures-only product decision removes
per-run subfolders, plotted-source CSV files, QC workbooks, and JSON manifests.
App close defers while an active plotting thread cancels cooperatively.
Non-finite values are handled
consistently as missing, figures use the shared 6.5-inch publication-width
contract, and selected group labels are mapped to canonical project group IDs
during aggregation. The expanded Plot Generator focused gate passes 106 locally
safe tests. Its registered pytest-qt cancellation, close-deferral, and
multi-group lifecycle smokes remain CI-only.
Final local SNR handoff verification passed Plot Generator (106 tests),
processing (359 tests and one skip), project I/O (83 tests), Stats (384 tests),
strict documentation, and repo precommit (1,685 tests and three skips), plus
the applicable GUI/path/structure audits, Ruff, and compilation checks.

SNR stale-state recovery progress on 2026-08-16: managed-provenance failures
now carry the affected project identity and reason to one shared Main App
**Post-processing Required** dialog. Acceptance launches the existing
post-processing activity workflow and reuses processed workbooks without EEG
preprocessing. SNR participant exclusions default to No, mark downstream
frequency outputs stale when accepted, and use the same recovery action.

LORETA source-cohort follow-up on 2026-08-16: the shared L2/eLORETA input plan
now applies the project's saved whole-participant and participant-condition QC
exclusions before derivative loading and sample-count selection. Large
available-case omission sets use bounded log summaries while exact participant,
condition, and reason rows remain in source validation artifacts.

Scalp Maps release-closeout progress on 2026-08-16: managed runs now use the
canonical processed-workbook index and exact project Excel root, resolve one
group before aggregation, and route All groups to separate group folders.
Active workbook/schema/value failures are fatal rather than silently reducing
the cohort. Missing sensors are omitted instead of zero-filled, with minimum
coverage enforced. Multi-group figure publication is transactional and
cancellation is cooperative through worker exit; stale processing uses the
shared recovery dialog. The focused Scalp Maps gate passed 73 tests, project
I/O passed 83, and Stats passed 384. Repo precommit reached 1,713 passing tests
and three skips; its four Windows sandbox-only named-pipe/memmap ACL failures
all passed on an exact normal-ACL rerun.

Scalp Maps comparison follow-up on 2026-08-16: exactly-two-group projects can
now render one selected condition with the two canonical groups as side-by-side
columns. Group means remain independent, color limits are shared per metric,
and the comparison is explicitly descriptive rather than a difference test.
Comparison mode publishes only its combined PNG/PDF figure pair at the base
Scalp Maps output. The embedded page now uses a vertically resizable scroll
surface so its Conditions/Settings and Output/Run cards cannot overlap at the
supported 1280 x 900 layout.

Main processing-page GUI cleanup on 2026-08-17: the persistent processing log
now opens from a focused **View Log** modal instead of consuming the bottom of
the home workspace. The Conditions editor expands into the recovered height,
and the Start Processing action remains anchored below it.

ROI selector port implementation completed locally on 2026-09-03: the
SSSEP-style visual BioSemi64 electrode picker is explicit v3 scope on
`codex/sssep-roi-selector`. It replaces the free-text-only experience on
**Settings > ROIs** while retaining the text rows as a compatibility fallback,
the existing FPVS settings schema and preset catalog, and all downstream ROI
mathematics and output contracts. Focused local code/state/consumer gates and
strict docs pass; the registered CI Qt suite and visible installed-app
acceptance remain. That pass must cover draft Cancel/Use behavior,
noncanonical-label preservation, outer Settings Save/Cancel/reopen, and
same-session refresh of cached ROI consumers.

Baseline: `v2.1.2`. At the 2026-08-16 audit, `main` was 217 commits and 633
changed files beyond that tag, while `src/config.py` still reported `2.1.2`.
That scope warrants a major release rather than a patch release.

## Release Thesis

Version 3 is a consolidation release. Its core promise is trustworthy FPVS
processing plus two default tools:

- Free Harmonic Clustering;
- SNR Plots.

The following tools remain opt-in beta surfaces: Scalp Maps, Standard FPVS
Screening, Sensitivity Analysis, LORETA Visualizer, Sequence Figure, and
Individual Detectability. They must open safely from the
packaged app, but finishing or promoting them is not a v3.0.0 requirement.

"Default" is a support tier, not a universal scientific-validation claim.
Free Harmonic Clustering has a reviewed powered null-calibration receipt. SNR
Plots is a descriptive visualization/export tool whose release bar is faithful
plotted values and reliable output behavior. Scalp Maps retains its completed
correctness work while remaining explicitly beta.

General study-specific inference remains export-first. The Toolbox owns FPVS
processing, QC, canonical identities, harmonic provenance, domain-specific
summaries, and the locked Free Harmonic Clustering procedure. Custom models,
covariates, random-effects structures, and study-specific contrasts belong in
R/RStudio, JASP, or reviewed analysis scripts.

## Already Established — Do Not Redo

- [x] Beta tools are centrally registered, hidden by default, and pass through
      one shared once-per-session acknowledgement.
- [x] Free Harmonic Clustering's 4,000-replicate x 10,000-assignment powered
      null study passed its frozen acceptance envelope and has a reviewed
      durable receipt.
- [x] Routine FHC CI retains a small deterministic regression smoke.
- [x] Shared PySide6 style tokens, typography, cards, action rows, status
      banners, tool-information dialogs, and stable/beta sidebar sections
      already exist.
- [x] Publication figures have a shared PNG/PDF, 600 dpi, and Arial contract.
- [x] Multi-group manifests, processing output routing, and the canonical
      project dataset index are implemented.

Do not rerun the powered FHC calibration merely for v3 branding, copy, GUI,
packaging, or export-layout work. Reassess it only if automatic selection,
normalization, adjacency, cluster/t-statistic math, permutation generation,
threshold/p-value rules, or relevant numerical dependencies change.

## P0 — Release Blockers

### 1. Freeze the v3 product boundary

- [ ] Confirm the default and beta tool lists above in runtime, user docs, and
      release notes.
- [ ] Reconcile the execution-plan directory: remove completed plans, move
      implemented future plans out of the backlog, and make the quality-status
      page agree with the remaining active plans.
- [ ] Freeze v3-compatible processing defaults and document every intentional
      difference between a new v3 project and an existing v2.1.2 project.
- [ ] Prove that an existing project with no versioned harmonic profile retains
      the legacy profile and does not silently acquire new numerical results.
- [ ] Keep `PROJECT_SCHEMA_VERSION` independent from the app-version bump;
      change it only if the manifest schema actually changes.

### 2. Correct the two default tools and stabilize Scalp Maps beta

#### Free Harmonic Clustering

- [x] Confirm the current numerical-source and dependency fingerprints against
      the reviewed calibration boundary. If only presentation/export code
      changed, retain the existing powered receipt.
- [x] Move exact workbook ingestion to the neutral `Main_App.io` owner, retain
      the Stats compatibility adapter, and prove exact read/cache/error
      behavior plus the absence of direct or transitive Stats XLSX-reader
      imports from the FHC preparation path.
- [x] Run the routine deterministic regression and focused backend/export suite
      after the reader relocation.
- [ ] Run the registered CI-only embedded-page smoke at the final closeout/RC
      commit.
- [ ] From the exact packaged RC, visibly reproduce the canonical ACR Neutral
      Happy comparison: n=18 versus n=16, retained H1/H2, positive H1 cluster
      at C1/Cz/CPz, and raw sign-specific p approximately `.0043`.
- [ ] From the packaged app, complete one small paired or independent run and
      verify cancellation, non-overwriting run output, manifest/provenance, and
      result-folder actions. This can share the same installed-app session as
      the canonical ACR reproduction and is not another powered calibration.

#### SNR Plots

- [x] Before a two-condition overlay, require identical physical frequency
      grids. Reject mismatched grids with a clear message instead of plotting
      condition B against condition A's x-axis.
- [x] Make cancellation cooperative. Keep the worker/thread and navigation
      locked until the worker actually returns; never permit overlapping
      generation or writes after a visible cancel.
- [x] For project-backed runs, take base/oddball rates and expected spectral-QC
      frequencies from frozen project/processing provenance, not mutable
      application-global settings.
- [x] Keep SNR output intentionally figures-only: write matching PNG/PDF files
      directly into `2 - SNR Plots`, without per-run folders, spreadsheets, QC
      workbooks, or manifests.
- [x] Add focused regression coverage for mismatched grids, cancellation,
      direct figure output, spectral-QC behavior, PDF/PNG figure dimensions, and
      participant counts.
- [x] Streamline the default-tool surface with a compact SNR header, corrected
      figures-only About copy, specific folder and generation actions, inline
      running/completion feedback, a focused on-demand generation log, and
      accessible control names. The idle page has no status/progress rows or
      page-level scrolling. Keep hard failures and scientific/exclusion
      decisions modal.

#### Scalp Maps

- [x] Replace recursive condition-folder workbook discovery and filename-based
      participant inference with `Main_App.projects.dataset_index`.
- [x] Select one canonical `group_id` before aggregation. An all-groups action
      must create separate group outputs; it must never pool groups implicitly.
- [x] Apply shared participant-condition exclusions, duplicate preference, and
      dataset diagnostics. Hard-fail empty, unassigned, or ambiguous cohorts.
- [x] Keep Scalp Maps output intentionally figures-only: write matching PNG/PDF
      files without source-data workbooks or other auxiliary artifacts.
- [x] Treat an unreadable active workbook, missing requested sheet, or missing
      exact harmonic column as a fatal requested-output error unless a future
      explicit partial-cohort mode is designed and visibly labelled.
- [x] Stop converting missing sensors to numerical zero. Either render only
      defined channels with a documented coverage rule or block insufficient
      coverage; missing data must not affect interpolation or color scaling as
      if it were measured zero.
- [x] Make cancellation explicit and cooperative through reading, aggregation,
      rendering, and atomic figure publication. A cancelled run must not emit
      a normal completion result.
- [x] Add focused and CI-only GUI coverage for single/multi-group selection,
      one-bad-workbook failure, sensor coverage, busy/navigation state,
      cancellation, and completion/error status.

### 3. Qualify processing and project compatibility

- [ ] Run the representative-project bitwise/performance smoke that remains
      open in `bitwise-pipeline-performance.md`, including scientific workbook
      sheets, QC output, and harmonic output comparison.
- [ ] Exercise both a normal internal-drive project and one slow/external-drive
      project, or explicitly accept and document the unmeasured external-drive
      risk for v3.0.0.
- [ ] Verify create, open, process, cancel, resume/rebuild, cache invalidation,
      participant-condition exclusion, and multi-group output routing on the
      RC commit.
- [ ] Verify that project files, settings, logs, outputs, and the root
      `.fpvs_cache` remain outside installer replacement/deletion scope.

### 4. Make the Windows artifact testable

- [ ] Change `FPVS_TOOLBOX_VERSION` only when the RC branch is frozen; use an
      RC such as `3.0.0rc1`, then `3.0.0` for the stable rebuild.
- [ ] Separate display/package version from Inno's numeric Windows file version
      so prerelease labels do not enter `VersionInfoVersion`.
- [ ] Remove or synchronize the Inno script's stale `2.1.0` fallback and test
      version drift as a packaging error.
- [ ] Add `scripts/packaging/smoke_packaged_app.ps1`. A release build must fail
      when the smoke is missing or fails; it must not silently skip it.
- [ ] Have the packaged smoke launch the frozen executable, verify the reported
      version, import lazy runtime dependencies, reach the Main Window, and
      exit deterministically without an offscreen Qt workaround.
- [ ] Install Inno Setup 6 in the release environment and build from a clean
      Windows 11 checkout/environment.
- [ ] Produce `FPVSToolbox-<version>-setup.exe` and record its SHA-256.
- [ ] Add a Windows packaging workflow or preserve equivalent signed-off manual
      evidence for every RC. Existing Ubuntu source CI does not qualify the
      installer.

### 5. Perform one compact installed-app acceptance pass

- [ ] Fresh-install the RC in a clean Windows account/VM; launch, close, and
      relaunch it.
- [ ] Upgrade in place from v2.1.2 and confirm projects, settings, logs, and
      generated outputs are preserved.
- [ ] Create/open a project, process a small representative dataset, inspect QC,
      and generate FHC and SNR Plots outputs.
- [ ] Enable Beta Tools and open each beta surface far enough to catch missing
      frozen imports/plugins; run a representative Scalp Maps export and confirm
      the shared beta notice appears once per tool per session.
- [ ] Verify About, title bar, update dialog, installer metadata, and artifact
      name all report the intended version.
- [ ] Exercise installer `/RELAUNCH=1`, then uninstall and verify user data is
      not removed unexpectedly.

## P1 — Consolidation Before the RC Freeze

### Stable-tool boundaries and redundant code

- [ ] Default tools must not depend on beta-tool GUI or private implementation
      modules. Move neutral exact-XLSX reading, ROI settings/constants, and
      processing-owned harmonic metadata behind appropriate `Main_App.io`,
      `Main_App.projects`, or `Main_App.processing` public APIs; retain thin
      compatibility adapters where needed.
- [ ] Consolidate the three selected-column XLSX readers only after exact-value,
      column-order, missing-column, and performance characterization tests are
      in place.
- [x] Remove Scalp Maps' dependency on Plot Generator's private participant-ID
      parser by using canonical dataset records.
- [ ] Share run/cancel/completion and output-folder behavior through existing
      PySide6 components where behavior is genuinely identical.
- [ ] Split maintenance hotspots only behind characterization tests. Start with
      GUI orchestration and export sheet builders; do not refactor FHC numerical
      kernels merely to reduce line counts before release.
- [ ] Tighten broad exception handling only along the two default-tool paths,
      preserving intentional best-effort boundaries and adding path/operation
      context to logs.

### User-facing UX and v3 identity

- [ ] Keep the existing PySide6 component/theme architecture. Do not perform a
      full reskin, workflow rearrangement, or per-tool stylesheet rewrite.
- [ ] Consider renaming `Quick Tools` to `Core Tools` or `Supported Tools`.
      Avoid the scientifically broad label `Validated Tools` unless the scope
      of validation is stated for every entry.
- [ ] Give both default tools the same header, About/help affordance,
      status/progress placement, Run/Cancel behavior, completion summary, and
      output-location action.
- [x] Replace generic stable-tool labels such as `Browse...`, `Open...`,
      `Generate`, and `Reset to Default settings` with specific action verbs.
- [ ] Move locally correctable input errors to inline `StatusBanner` feedback;
      retain modal dialogs for destructive decisions and hard failures.
- [ ] Add accessible names/descriptions through shared button/path/status
      factories, visible keyboard focus for shared controls, and a documented
      1280 x 900 keyboard/layout smoke.
- [ ] Add the visual BioSemi64 selector to **Settings > ROIs**, retaining the
      existing app-level ROI schema, FPVS preset definitions, text fallback,
      and same-session refresh for cached consumers.
- [ ] Add a restrained version-3 identity cue to the landing/header area, such
      as a config-derived `FPVS Toolbox 3` badge plus one subtle harmonic or
      waveform motif. Preserve the quiet scientific-desktop palette.
- [ ] Update About/What's New and documentation screenshots after workflows and
      copy are frozen. A new icon is optional, not a release blocker.

## P1 — Documentation and Release Notes

- [ ] Add a v3 release-notes page, v2.1.2-to-v3 migration guide, concise
      processing quick-start, and Windows install/update instructions to the
      user documentation navigation.
- [ ] State the exact default/beta support boundary and the export-first policy
      for study-specific statistics.
- [ ] Document new-project versus legacy-project harmonic-profile behavior,
      multi-group layout, exclusions, cache/freshness behavior, and any output
      schema changes.
- [ ] Verify every user-visible name, screenshot, path, method identifier, and
      reporting example against the RC build.
- [ ] Draft release notes from the inventory below, then verify every claim
      against `v2.1.2..v3.0.0` before publication.

### Major feature inventory over v2.1.2

- Multi-group project manifests, processing, group-safe output routing, and a
  canonical processed-workbook index.
- Expanded preprocessing/QC: condition-aware preflight, artifact freshness,
  FullFFT provenance, harmonic/frequency review, exclusions, cache
  invalidation, and FFT multi-notch support.
- Versioned harmonic-selection strategies with backward-compatible legacy
  resolution and deterministic downstream rebuilds.
- Free Harmonic Clustering as a default tool with paired/independent cluster
  permutation workflows and reviewed powered null-calibration evidence.
- Embedded PySide6 tool workflows with centralized default/beta navigation.
- A new opt-in beta suite: Scalp Maps, Standard FPVS Screening, Sensitivity
  Analysis, LORETA Visualizer, Sequence Figure, and
  Individual Detectability.

### Minor feature inventory over v2.1.2

- Multi-group SNR overlays, sample-count/legend improvements, paired exports,
  and spectral-QC warnings.
- Publication-oriented Scalp Maps and shared 600-dpi PNG/PDF figure styling.
- Bitwise-preserving preprocessing/post-processing speedups and lower repeated
  workbook/cache I/O.
- Shared GUI components, vector sidebar icons, consistent subsection headings,
  tool-information dialogs, and the centralized beta acknowledgement.
- Expanded compatibility checks, verification/audit coverage, user methods
  documentation, and Linux source/CI support.

## Verification Gate

Run focused checks before the repository-wide gate:

```console
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope plot-generator --tier focused
python .agents/scripts/verify.py --scope publication-maps --tier focused
python .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
python .agents/scripts/verify.py --scope gui --tier focused
python .agents/scripts/verify.py --scope updates --tier focused
python .agents/scripts/verify.py --scope figures --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

PySide6/pytest-qt execution remains CI-only unless an explicitly approved
visible environment is used. The installed-app acceptance pass is visible and
must use the actual packaged Windows build.

## Explicitly Deferred Beyond v3.0.0

- Promoting or completing any beta tool.
- Generalizing Standard FPVS Screening into a publication model builder.
- New inferential methods or harmonic-selection profiles.
- LORETA inverse-model caching and other beta-only performance work.
- FHC result-history browsing, topographic/heatmap result views, or broad
  numerical-module refactors.
- Reduced-motion polish for the decorative brain pulse currently used only by
  the beta Standard FPVS Screening surface.
- A whole-app visual redesign, new theme system, or decorative animation pass.
- Repo-wide technical-debt sweeps unrelated to a default-tool or release path.

## Exit Criteria

Version 3.0.0 is ready only when:

- [ ] Every P0 item is complete with evidence linked from this plan.
- [ ] P1 items are complete or individually deferred with an owner, reason, and
      post-v3 destination; no silent deferral remains.
- [ ] Source CI, focused gates, and repo precommit are green at the release
      commit.
- [ ] The Windows executable/installer smoke and installed-app acceptance pass
      are green for the exact uploaded artifact.
- [ ] Release notes, migration guidance, checksum, and final `3.0.0` version
      metadata are published together.
