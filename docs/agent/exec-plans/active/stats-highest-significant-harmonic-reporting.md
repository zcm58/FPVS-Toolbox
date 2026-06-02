# Stats Highest Significant Harmonic Reporting

## Status

Active plan for branch `codex/publication-scalp-maps-harmonics`.

This plan was tightened against the current code on 2026-06-02. Read it before
changing Stats DV metadata, Stats-ready exports, or Stats report metadata.

## Goal

Expose the highest harmonic selected as significant by the Stats group-level
significant-harmonics policy.

The value should be easy to find in Stats outputs so users can report it or use
it as an input for publication/export workflows without manually inspecting the
full harmonic-selection table.

## Non-Negotiable Constraints

- Do not change the locked Stats group-significant selection method.
- Do not change candidate generation, locked 1.2 Hz oddball spacing, exact
  column matching, z > 1.64 selection, noise-window bins, base-rate overlap
  exclusion, or selected BCA summation.
- Do not use workbook `Z Score`, SNR, ROI-specific z values, or nearest-bin
  matching to determine the highest significant harmonic.
- Do not report `_plan_required_full_fft_columns(...)` local `highest_k` as the
  highest significant harmonic. That variable is only the highest candidate
  index implied by the max frequency limit.
- Do not add harmonic metadata columns to the stats-ready `Long_Format` or
  `Wide_Format` analysis sheets.
- Keep `Harmonic_Selection` row-level details intact.
- Keep this change additive. Existing selected-harmonics metadata and workbook
  columns should remain stable unless tests are intentionally updated for a new
  summary sheet.

## Current Code Anchors

Primary source:

- `src/Tools/Stats/analysis/dv_policy_group_significant.py`
  - `GroupSignificantHarmonicSelection.selected_harmonics_hz`
  - `GroupSignificantHarmonicSelection.oddball_frequency_hz`
  - `GroupSignificantHarmonicSelection.rows`
  - `GroupSignificantHarmonicSelection.to_metadata(...)`
  - `build_group_significant_harmonic_selection(...)`

Current export/report plumbing:

- `src/Tools/Stats/workers/stats_workers.py`
  - `_summarize_dv_metadata_for_export(...)` already emits
    `selected_harmonics_hz` as a semicolon-delimited scalar metadata field.
- `src/Tools/Stats/ui/stats_window_exports.py`
  - DV Definition export currently writes "Included harmonics (Hz)",
    selection scope, z threshold, and SNR-used flags.
- `src/Tools/Stats/io/stats_ready_export.py`
  - `HARMONIC_SELECTION_SHEET = "Harmonic_Selection"`.
  - `HARMONIC_SELECTION_COLUMNS` define row-level harmonic details.
  - `_build_harmonic_selection_frame(...)` routes group metadata to
    `_group_significant_selection_rows(...)`.

Existing tests to extend:

- `tests/stats/analysis/test_fixed_predefined_harmonics.py`
  - group-significant selection and metadata tests.
- `tests/stats/io/test_stats_ready_export.py`
  - stats-ready `Harmonic_Selection` export tests.
- `tests/stats/analysis/test_baseline_vs_zero.py`
  - result metadata already asserts `selected_harmonics_hz`.

## Definitions

For group-significant policy:

- `highest_significant_harmonic_hz`
  - `max(selected_harmonics_hz)` after finite numeric filtering.
- `highest_significant_harmonic_index`
  - rounded integer `highest_significant_harmonic_hz / oddball_frequency_hz`.
  - With locked oddball 1.2 Hz, 7.2 Hz is index 6.
- `highest_significant_harmonic_label`
  - optional human-readable text such as `7.2 Hz (6th 1.2 Hz harmonic)`.
  - Add this only if it simplifies report text; do not make tests depend on
    ordinal grammar unless necessary.

For fixed/predefined policy:

- Use `highest_selected_harmonic_hz` and
  `highest_selected_harmonic_index` if adding shared fixed-policy metadata.
- Do not call fixed/predefined harmonics "significant"; they were selected by
  user definition, not the group-significant z test.

## Implementation Order

### 1. Add Small Helper Functions

Add helper functions in the narrowest Stats module that owns the metadata.
Preferred location: `src/Tools/Stats/analysis/dv_policy_group_significant.py`
near `GroupSignificantHarmonicSelection.to_metadata(...)`.

Suggested helpers:

- `_finite_harmonic_values(values: Sequence[object]) -> list[float]`
- `_harmonic_index_for_frequency(frequency_hz: float, oddball_hz: float) -> int | None`
- `_highest_selected_harmonic_metadata(values, oddball_hz, prefix) -> dict[str, object]`

Guidelines:

- Return `math.nan` or omit fields only if the selected list is empty. The
  group-significant policy normally raises before producing empty selected
  harmonics.
- Use defensive finite-value checks.
- Use `round(...)` for the harmonic index and verify the rounded index maps
  back to the frequency within the existing matching tolerance.
- Keep helpers pure and easy to test.

### 2. Serialize Group Metadata

In `GroupSignificantHarmonicSelection.to_metadata(...)`, add:

- `highest_significant_harmonic_hz`
- `highest_significant_harmonic_index`

Optional:

- `highest_significant_harmonic_label`

Do not remove or rename:

- `common_harmonics_hz`
- `selected_harmonics_hz`
- `selected_columns`
- `selected_bin_indices`
- `selection_z_by_harmonic`
- `selection_rows`

### 3. Add Worker Scalar Metadata

In `stats_workers.py::_summarize_dv_metadata_for_export(...)`, for
`group_significant_harmonics`, add scalar entries:

- `highest_significant_harmonic_hz`
- `highest_significant_harmonic_index`

Keep existing `selected_harmonics_hz` as the current semicolon-delimited string.

For fixed/predefined metadata, either leave unchanged or add clearly named
`highest_selected_harmonic_hz/index`. If added, update tests to show it is not
significance-based.

### 4. Update DV Definition Export

In `src/Tools/Stats/ui/stats_window_exports.py`, add summary rows in the
group-significant branch:

- `Highest significant harmonic (Hz)`
- `Highest significant harmonic index`

Place them near `Included harmonics (Hz)` so the exported DV definition is easy
to scan.

If adding fixed/predefined fields, label them:

- `Highest selected harmonic (Hz)`
- `Highest selected harmonic index`

Do not add these values to per-ROI harmonic rows.

### 5. Add Stats-Ready Summary Sheet

In `src/Tools/Stats/io/stats_ready_export.py`, add a compact summary sheet
rather than changing analysis sheets.

Preferred constants:

- `SELECTION_SUMMARY_SHEET = "Selection_Summary"`
- `SELECTION_SUMMARY_COLUMNS = ["key", "value"]`

Preferred content for group-significant policy:

- harmonic policy
- harmonic policy label
- selection scope
- base frequency Hz
- oddball frequency Hz
- z threshold
- selected harmonics Hz
- highest significant harmonic Hz
- highest significant harmonic index
- selection source sheet
- z score source
- noise window bins
- applied uniformly across participants/conditions/ROIs
- SNR used for statistics

Rules:

- Keep `Long_Format` columns exactly:
  `subject_id`, `group_id`, `condition`, `roi`, `summed_bca_uv`.
- Keep `Wide_Format` value columns unchanged.
- Keep `Harmonic_Selection` columns unchanged unless a separate, explicit
  row-detail need appears.
- Make the sheet useful for both group-significant and fixed/predefined policy,
  but use "significant" wording only for group-significant metadata.

### 6. Add Log/Plain Text Report Line

Where the Stats run currently logs selected harmonics after
`build_group_significant_harmonic_selection(...)`, add a concise message:

```text
Highest significant oddball harmonic: 7.2 Hz (index 6).
```

Do not duplicate this line in every participant/condition loop. It belongs once
after selection is built.

## Tests To Update

### `tests/stats/analysis/test_fixed_predefined_harmonics.py`

Extend `test_group_significant_policy_selects_common_grand_average_harmonics`:

- call `selection.to_metadata()`;
- assert `highest_significant_harmonic_hz == pytest.approx(7.2)`;
- assert `highest_significant_harmonic_index == 6`.

Extend `test_group_significant_policy_sums_selected_common_bca_for_every_roi`:

- assert `metadata["group_significant_harmonics"]` contains the same fields.

### `tests/stats/analysis/test_baseline_vs_zero.py`

Where result metadata currently asserts `selected_harmonics_hz`, add assertions
for the new worker scalar metadata if the fixture uses fixed/predefined policy.
Use fixed-policy field names if fixed support is added; otherwise add a
group-significant worker metadata test elsewhere.

### `tests/stats/io/test_stats_ready_export.py`

Update `test_build_stats_ready_frames_exports_group_significant_metadata`:

- include the new highest fields in `group_meta`;
- assert `Selection_Summary` exists;
- assert summary rows contain highest significant harmonic Hz/index;
- assert `Long_Format` does not contain highest/selected harmonic metadata.

Update workbook-write tests to account for the additional sheet name.

## Verification Plan

Use `.venv` in this checkout unless `.venv1` is restored.

```powershell
.\.venv\Scripts\python.exe -m py_compile src\Tools\Stats\analysis\dv_policy_group_significant.py src\Tools\Stats\workers\stats_workers.py src\Tools\Stats\io\stats_ready_export.py src\Tools\Stats\ui\stats_window_exports.py
.\.venv\Scripts\python.exe -m pytest tests\stats\analysis\test_fixed_predefined_harmonics.py tests\stats\io\test_stats_ready_export.py tests\stats\analysis\test_baseline_vs_zero.py -q
.\.venv\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-structure
.\.venv\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-reporting-legibility
```

Do not run offscreen Qt workflows locally. If GUI report/export behavior needs a
smoke check, use a visible manual Stats run and confirm:

- the log reports selected harmonics and highest significant harmonic once;
- `Summed BCA DV Definition.xlsx` includes highest significant harmonic rows;
- `Stats_Ready_Summed_BCA.xlsx` includes `Selection_Summary`;
- `Long_Format` and `Wide_Format` remain analysis-ready.

## Completion Criteria

- Group-significant Stats metadata exposes highest significant harmonic Hz and
  harmonic index.
- Pipeline result metadata and DV Definition export surface the same values.
- Stats-ready export provides the values in a summary sheet while preserving
  analysis-sheet schemas.
- Existing selected harmonic details, z scores, exact-column behavior, and BCA
  aggregation remain unchanged.

## Persistence Addendum

The selected group-significant harmonic list may be reused across Stats runs
only when the saved project metadata exactly matches the current analysis
inputs. Persisted entries live in `project.json` under
`tools.stats.group_significant_harmonics_cache` and are keyed by final
participants, selected conditions, source workbook path/size/mtime, Stats
harmonic settings, and the current project preprocessing/event-map signature.

Changing preprocessing settings such as `high_pass`, `low_pass`, downsampling,
epoch window, references, channel limits, stim channel, event map, method
version, or source workbook files must force recalculation. Reused selections
must still validate exact BCA columns before export/statistics, and project
saves must preserve the `tools.stats` namespace written by Stats workers.
