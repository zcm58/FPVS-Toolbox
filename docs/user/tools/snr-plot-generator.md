# SNR Plots

SNR Plots creates region-of-interest (ROI) spectra from the `FullSNR` sheets in
processed FPVS workbooks. It averages electrodes within each selected ROI and
participants within each plotted condition or project group.

## Before You Start

Process the relevant BDF files first. The selected Excel root should contain a
subfolder for each condition, with one processed workbook per participant. Each
workbook must include the `FullSNR` sheet; this tool does not recompute SNR from
FFT amplitudes.

For a managed project, SNR Plots uses the base and oddball frequencies frozen
with the current processing-owned FullFFT provenance. It also uses that
record's exact active workbook family. Missing or stale provenance blocks the
run and opens a **Post-processing Required** explanation. Choose **Run
Post-processing** to refresh the downstream project state from the existing
processed workbooks; EEG preprocessing is not rerun. Changing current
application settings cannot silently relabel an older processed project. A
manually browsed unmanaged folder retains the legacy application-settings
fallback and is identified as such in the run log.

The ROI list comes from the current Toolbox settings. Confirm the ROI electrode
definitions before generating figures.

## Single-Group Projects

For a single-group project, you can:

- create a separate spectrum for one condition or queue all conditions;
- choose one ROI or generate plots for all defined ROIs; and
- overlay two different conditions on the same plot.

Each curve is the participant-average SNR spectrum for that condition and ROI.
Its legend includes the number of participants contributing at least one finite
value to the ROI.

## Multi-Group Projects

When the active `project.json` defines multiple groups and the canonical project
Excel root is selected, Group Options become available. Multi-group plotting is
a one-condition group-overlay workflow:

- choose one condition;
- choose one or more project groups; and
- generate the required group overlay, which draws a separate
  participant-average curve for each selected group.

Group overlay is enabled automatically and cannot be turned off for a canonical
multi-group project. This prevents an unlabeled pooled all-groups curve from
being mistaken for a project-group result. Workbooks from intentionally
unselected groups are skipped before workbook and spectral-QC reads, recorded
in the worker's internal disposition state, and logged as information rather
than completion warnings.

Group membership comes from the participant metadata in `project.json`, not
from output-folder names. Workbooks for a multi-group project may be nested as
`<Excel Root>/<Condition>/<Group>/<Workbook>`, but a workbook without a matching
project participant assignment is omitted from the group curves and reported in
the log.

Selected display labels remain mapped to canonical project group IDs during
aggregation, so renamed folders or presentation labels cannot change group
identity.

Condition A/B overlay is hidden in multi-group mode because group overlay is the
supported comparison for that mode. The first and second color and legend
controls map to the first two selected groups. Additional selected groups use
automatic distinct colors, marker shapes, and their project labels.

Each curve label includes the number of participants that contributed finite
SNR values to that ROI, such as `Control (n=18)`. If a selected group has no
usable data for an ROI, the tool names that group and ROI in the log and run
warning count, then omits it from that figure. If every selected group is empty,
the tool skips the group-overlay figure instead of substituting a pooled
all-participant curve.

## Figure Options

You can set legend labels, axis labels, axis limits, colors, and the frequency
range read from each workbook. Figure filenames and titles follow the selected
condition and ROI. Optional spectral quality-control
checks can flag suspicious electrode-level spectra in the completion warning
without silently changing the plotted source values.

## Outputs

The tool writes matching 600-DPI `.png` and `.pdf` files directly into the
selected output folder, which defaults to the active project's
`2 - SNR Plots` folder. It does not create a per-run subfolder, source-data
spreadsheet, QC workbook, or JSON manifest. Ordinary figures use
`<condition> - <ROI>`. Group overlays use
`<condition> - <ROI>_group_overlay`, so they remain distinct from ordinary
figures.

The compact page hides status and progress while idle. They appear while a run
is active; progress hides again when the run ends, while completion or warning
status remains available. Choose **View Log** for full generation details and
**Open Plot Folder** to review the figures. Successful runs do not interrupt
the workflow with a confirmation dialog.

When spectral QC is enabled, missing or insufficient evidence is surfaced as a
warning rather than silently presented as a completed QC pass. Spectral-QC
flags remain report-only and do not change plotted values.

When QC flags support an optional whole-participant exclusion, the Toolbox
offers to save that exclusion only if the figures came from the currently
active managed project. Browsing an unmanaged folder or a different project
never changes the active project's exclusion settings. The confirmation
defaults to **No**. If an exclusion is accepted, the shared post-processing
dialog explains the resulting stale state and can launch the required refresh.

Cancel remains visibly pending until the current worker actually stops; a
second generation cannot overlap it. Figure files that finished saving before
cancellation are kept, while any later queued conditions remain cancelled.
Closing FPVS Toolbox during generation requests the same cooperative cancel and
defers closing until the worker has stopped.

All participant workbooks contributing to one figure must use the same FullSNR
frequency grid. A workbook with a different grid is skipped and reported rather
than being averaged into the wrong frequency positions. A two-condition overlay
also requires the two accepted condition grids to match. If they do not, the
tool reports the mismatch and writes no overlay figure.

SNR is a descriptive frequency-domain normalization. A peak can help show that
the target response stands above neighboring frequencies, but it is not by
itself an inferential significance test.

## Basic Steps

1. Open **SNR Plots** after processing the project.
2. Confirm the **Processed Excel Folder** and **Plot Output Folder**.
3. Select the condition and ROI scope.
4. For a single-group project, optionally enable a two-condition overlay.
5. For a multi-group project, select the groups to include; group overlay is
   required and enabled automatically.
6. Adjust labels, ranges, colors, and optional spectral QC.
7. Select **Generate SNR Plots**, then use **Open Plot Folder** to review the
   matching PNG/PDF figures in `2 - SNR Plots`.

## References

- Volfart, A., et al. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- Hauk, O., et al. (2021). [Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*, 118460.
- [SNR Plots implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Plot_Generator).
