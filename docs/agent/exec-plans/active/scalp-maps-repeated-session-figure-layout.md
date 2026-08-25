# Scalp Maps Repeated-Session Figure Layout

## Status

Implementation complete. Awaiting visible/manual user review; no code work is
pending.

## Goal

Refine only the multi-group repeated-session scalp-map grid so its PNG/PDF
assets fit a US Letter Word page at the full 6.5-inch text width, contain no
bottom descriptive/confound footer, keep figure and panel titles unclipped,
and distinguish the two canonical group columns clearly. Also reclaim the
Generate Maps workspace by moving output controls and the full generation log
to Advanced Settings, with the log available on demand in a modal dialog.

## Locked Scope And Guardrails

- The affected layout owner is
  `Tools.Publication_Maps.session_rendering._render_session_panel_set`. Treat
  “every figure” as every 2-row or optional 3-row repeated-session grid. Do not
  change single-group, paired-condition, or ordinary two-group appearance.
- Establish explicit immutable layout owners for ordinary single-map,
  paired-condition, ordinary two-group comparison, and repeated-session
  figures. Shared drawing, color, and typography primitives may remain shared,
  but caller-specific geometry must be independently editable. Preserve the
  current appearance of the first three; only repeated-session changes here.
- Keep exact aggregation, group/session order, participant and paired `n`,
  shared color limits, difference-map math, colorbar roles, missing-data
  handling, filenames, selected output root, transactional publication, and
  cancellation behavior. Continue calculating the counts for internal panel
  data and validation, but omit visit indices and all sample-size annotations
  from repeated-session figure titles.
- Preserve matching PNG/PDF, 600 DPI, Arial figure typography, exact 6.5-inch
  width, and a conservative portrait-page height target no greater than 9
  inches. Do not change shared `_save_figure` behavior or add tight-bounding-box
  cropping.
- Remove the repeated-grid `FIXED_ORDER_CAVEAT` from the figure artwork, GUI,
  help, and session state. Retain the repeated-session 6.5-inch width rule.
- Use canonical project group labels; never hard-code birth-control names.
  Prefer a thin neutral divider derived from the actual column bounds and kept
  clear of titles, maps, and colorbars. Retain it only if visual QA confirms it
  improves separation; otherwise record the equivalent column-header solution.
- The existing repeated-session and v3 correctness contracts remain closed:
  this is presentation-only and must not introduce inferential wording.
- Keep condition/session selection, map types, status, progress, and
  **Generate Scalp Maps** on the first tab. Move the unchanged output-root
  picker/open action to a full-width Advanced Settings section; a valid saved
  or default destination must still let repeated-session users generate from
  the first tab without visiting Advanced Settings.
- Keep the repeated-session ready state concise: omit the idle readiness banner
  and instructional Advanced Settings paragraph while retaining validation,
  running, cancellation, and completion status. Generate, Cancel, and progress
  must share one control height. Do not show a separate two-group eligibility
  paragraph on Advanced Settings.
- Remove the embedded log viewer from the page. Add **View Generation Log** to
  Advanced Settings and open one reusable modal viewer that preserves the full
  current-run history, updates while hidden or open, clears only when a new run
  starts (or the user explicitly clears it), and does not alter worker/thread,
  cancellation, status, or error behavior.
- Preserve project-root resolution, output validation, QFileDialog Cancel
  behavior, and the 1280×900 no-page-scroll contract. The screenshots are
  visual references only; no displayed study path or group name is a runtime
  requirement.

## Implementation Slices

1. Characterize current ordinary renderers, then add the four explicit layout
   owners without changing non-repeated output.
2. Update the repeated-session style locally: remove the footer, reserve a
   non-overlapping title band, rebalance whitespace/height, and add the approved
   group-column separator treatment for both 2-row and 3-row grids.
3. Update scoped `AGENTS.md`, `tool_info.py`, and focused renderer/layout
   regressions; register any new test module in the publication-maps
   verification scope.
4. Add the tool-local modal generation-log viewer and move output destination,
   file-format summary, open-folder action, and log access to a full-width
   Advanced Settings section; leave generation orchestration unchanged.
5. Update CI-only Qt coverage and the manual smoke contract for tab ownership,
   unclipped controls, hidden/live log history, path validation, and generation
   from the first tab.

## Verification

- After drawing the canvas, assert exact 6.5-inch width, bounded height, no
  footer text, all titles inside the canvas, no suptitle/panel-title overlap,
  no visit/sample-size title annotations, correct colorbar count/labels, and
  repeated-only separator/header treatment. At the artifact level, verify PNG
  pixel dimensions/DPI metadata and PDF physical page size.
- Keep characterization coverage green for single-group, paired-condition,
  ordinary two-group, filenames, shared limits, and repeated-mode routing.
- CI Qt coverage asserts the page has no embedded log surface, Advanced
  Settings owns the output row and log button, the modal is reusable and shows
  messages received while hidden, and the first-tab action remains ready for a
  repeated-session project with a valid default output root.
- CI Qt coverage also asserts equal action-row control heights and the absence
  of the redundant Generate-tab guidance, repeated-session ready summary, and
  Advanced-tab two-group eligibility paragraph.
- Run `verify.py --scope figures --tier focused`, then
  `verify.py --scope publication-maps --tier focused`; add the `stats` scope
  only if implementation unexpectedly changes a numerical dependency. Do not
  run offscreen Qt.
- Visually inspect representative BCA, SNR, and Z-score PNG/PDF grids with and
  without the difference row, including long generic labels, inserted into Word
  at 6.5 inches and 100% scale.

## Progress

- [x] Style boundaries characterized and separated.
- [x] Repeated-session layout updated.
- [x] Advanced output/log workspace updated.
- [x] Contracts and focused tests updated.
- [x] Automated and renderer-level visual verification complete.
- [ ] Visible 1280×900 GUI and Word-placement smoke reserved for user/CI review.

## Verification Result

- The registered non-Qt Scalp Maps and figure-style suite passes: 104 tests.
- The v3 follow-up title cleanup keeps visit/sample-size metadata in panel data
  while exact rendered-title assertions prove that Visit, participant `n`, and
  paired `n` no longer appear in repeated-session artwork. The same 104-test
  suite remains green.
- GUI-focused static verification, Ruff, compilation, TOML parsing, and
  `git diff --check` pass. CI-only Qt tests were updated but not run locally.
- The follow-up Generate-tab cleanup also passes the focused GUI gate, Ruff,
  and syntax compilation. Registered CI-only Qt coverage now pins equal action
  heights, the hidden valid repeated-session ready banner, and removal of the
  redundant Generate/Advanced instructional copy.
- Six actual BioSemi64 stress renders (BCA/SNR/Z; 2-row/3-row) retain complete
  long labels without overlap or clipping, omit the footer, and keep the
  divider/colorbars inside exact 6.5×6.5-inch or 6.5×9-inch canvases.
- The `figures` and `publication-maps` drivers stop at eight unrelated existing
  hard-coded-path findings under untracked `outputs/rcads-*`; those files were
  left untouched, and the complete registered test lists were run directly.
