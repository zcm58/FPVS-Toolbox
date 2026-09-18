# FHC exploratory reporting

## Scope and decisions

Implement the requested reporting mode for repeated-batch comparisons with
global two-sided p < .05 that fail prespecified-family Holm correction. This
is a view over stored results, not a statistical-method change. Preserve all
preparation, selection, permutations, cluster p-values, correction families,
and primary result tables. Existing family Holm passes at <= .05, so the
exploratory filter requires family Holm > .05; full-batch Holm remains a
separate displayed value.

The shared headless `reporting.py` produces immutable primitive snapshots for
GUI and export, retains original outcome indices for filtered map navigation,
and details only clusters whose own two-sided p < .05. Use actual prepared
A/B labels and exact electrode membership by harmonic; do not infer a filled
sensor-by-harmonic product or pointwise significance. Descriptive effects,
fixed-order confounding, and the repeated-extension calibration limit remain
explicit in detailed reporting.

The GUI defaults to All comparisons, offers Exploratory findings, and opens a
focused details dialog without a new permanent pane or page-level scrolling.
New repeated bundles add a readable report, worksheet, and filtered CSVs to
the existing atomic publication/checksum transaction. No historical bundle,
source workbook, project metadata, or real project data is changed.

## Verification

Local non-Qt checks: focused FHC and GUI verification, headless reporting and
export tests, Ruff/compilation, then repository precommit. The initial focused
FHC command passed the GUI audit but stopped at the eight previously known
machine-path findings in unrelated untracked `outputs/rcads-*` artifacts.
Those files remain untouched; run the registered focused test targets directly
if that pre-existing gate continues to block them.

CI-only Qt coverage belongs in the existing registered FHC page tests. Do not
run Qt or offscreen scripts locally. Visible/manual path (pending): at
1280x900, finish a repeated batch and confirm All comparisons is the default;
switch to Exploratory findings, inspect a qualifying row and its three p-values,
open details and maps, and confirm original run identity/direction. Switch back
without a worker starting. Check an empty subset, a family-Holm pass that fails
full-batch Holm, and reset on setup/project change. Verify no clipping or page
scrollbar and confirm the readable report/worksheet/CSVs in Open Results Folder.

Final local verification:

- `.venv/Scripts/python.exe -m pytest tests/free_harmonic_clustering
  tests/project_io/test_main_app_xlsx_selected_reader.py -q`: **276 passed**,
  including strict threshold boundaries, signed-tail versus two-sided p,
  exact membership, unchanged primary results/tensors, checksummed publication,
  empty reports, and atomic cleanup if reporting fails.
- `.venv/Scripts/python.exe .agents/scripts/verify.py --scope gui --tier
  focused`: **472 passed**, with GUI import audit, Ruff, and compilation.
- Final Ruff and compilation of all eight changed Python files passed;
  `git diff --check` passed. Read-only independent review found no remaining
  correctness issues.
- `.venv/Scripts/python.exe .agents/scripts/verify.py --scope
  free-harmonic-clustering --tier focused` and `--scope repo --tier precommit`
  both stop at the same eight pre-existing path-audit findings in unrelated
  untracked `outputs/`. The FHC scope's registered tests were run directly as
  recorded above. The broad precommit gate is not a pass.
- Four new CI-only tests in the existing registered
  `tests/gui/test_free_harmonic_clustering_page.py` cover filtering, original
  map routing, no new analysis/export work, details, empty subsets, resets,
  and fit; two existing tests also cover the batch summary and unchanged
  legacy controls. Qt and the visible smoke path above remain pending.

## Changed files

- `src/Tools/Free_Harmonic_Clustering/reporting.py`
- `src/Tools/Free_Harmonic_Clustering/exports.py`
- `src/Tools/Free_Harmonic_Clustering/gui/page.py`
- `src/Tools/Free_Harmonic_Clustering/gui/result_details_dialog.py`
- `src/Tools/Free_Harmonic_Clustering/tool_info.py`
- `tests/free_harmonic_clustering/test_reporting.py`
- `tests/free_harmonic_clustering/test_exploratory_exports.py`
- `tests/gui/test_free_harmonic_clustering_page.py`
- `src/Tools/Free_Harmonic_Clustering/ARCHITECTURE.md`
- `docs/user/tools/free-harmonic-clustering.md`
- This execution plan.

Architecture and user docs were updated because reporting ownership, GUI
navigation, and additive completed-run artifacts changed. The numerical
analysis, preparation, input, model, and orchestration implementations remain
unchanged; no statistical method/version or new calibration claim is introduced.
