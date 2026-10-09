The Sequence_Figure directory owns the embedded FPVS Sequence Figure tool. It
builds publication-oriented illustrations of the stimulus sequence from
manually selected stimulus images.

Current ownership map:

- `renderer.py`: widget-free validation, image normalization, one-to-four
  condition rows, two-cycle timing scaffold drawing, and PNG/PDF/SVG export.
  It accepts either a legacy flat five-path tuple or nested condition tuples.
- `worker.py`: QThread-compatible QObject shell that runs renderer work and
  emits progress, errors, and completion without touching widgets.
- `gui.py`: embedded PySide6 page with bounded condition tabs for manual
  base/oddball image slots, 24-character condition labels, timing/styling
  controls, output folder selection, and dialog-based export feedback.

Default to three conditions; allow one through four. Keep hidden condition
inputs in memory when the count is reduced, but export only active conditions.
Use condition tabs and a flat two-column setup to fit the 1280x900 main shell
without page-level scrolling. Keep the shared information button and portable
file-manager helper. No settings or project-metadata persistence is added.

The main shell reuses this page and calls `set_project_root` from the current
`Project.project_root` on each open. A changed project resets the output default
and result-folder action while preserving manually selected images, labels,
and styling. Existing `Figures` folders supply the output default; otherwise
the output stays unselected and dialogs start from the current project root.
A running export retains its original immutable specification. Keep the page,
worker, and thread alive through thread cleanup; `has_active_generation` is the
shell's close/update guard. A completed export from an earlier project must not
restore that project's result-folder action on the refreshed page, including
when the user switches away and returns before completion.

Keep the fixed 13.333 x 7.5 inch figure and existing 600-DPI PNG/PDF/SVG export
surface. Grayscale-safe styling affects markers, not stimulus pixels. Optional
transparency applies only to PDF; PNG/SVG stay white. Wrap long condition labels
inside the figure margin without shrinking the shared Arial type size.

Keep this tool separate from `Tools.Plot_Generator`, which remains SNR-line-plot
only. Do not add EEG processing, SNR plotting, condition-folder sampling, or
project manifest writes here unless explicitly scoped.

Use the root `AGENTS.md` platform/environment policy and the initial audits in
`docs/agent/agent-index.md` before broad inspection.

For renderer changes, start with:

```console
python .agents/scripts/verify.py --scope sequence-figure --tier focused
```

Qt execution is CI-only by default; document a visible/manual embedded-page
smoke path for GUI wiring changes.

Visible project-switch smoke: in a disposable project A, open Sequence Figure,
select images and custom condition labels, and choose an output folder. Open
project B and reopen the tool; verify its existing `Figures` folder becomes the
default, or the output stays unselected and both picker dialogs start from B.
Verify images, labels, and styling are retained. Reopen the same project and
confirm a manual output choice persists; cancel both pickers and confirm no
inputs change. Start an export from A, switch to B, and reopen Sequence Figure;
verify the export completes to A's original selected folder, its completion
lists those paths, B's folder action stays disabled, and another export becomes
available after thread cleanup. Repeat A-to-B-to-A during export and confirm the
pending result does not enable A's reset folder action. Confirm PNG/PDF/SVG
output formats are unchanged.
