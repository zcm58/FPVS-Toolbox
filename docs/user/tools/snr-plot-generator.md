# SNR Plots

SNR Plots creates region-of-interest (ROI) spectra from the `FullSNR` sheets in
processed FPVS workbooks. It averages electrodes within each selected ROI and
participants within each plotted condition or project group.

## Before You Start

Process the relevant BDF files first. The selected Excel root should contain a
subfolder for each condition, with one processed workbook per participant. Each
workbook must include the `FullSNR` sheet; this tool does not recompute SNR from
FFT amplitudes.

The ROI list comes from the current Toolbox settings. Confirm the ROI electrode
definitions before generating figures.

## Single-Group Projects

For a single-group project, you can:

- create a separate spectrum for one condition or queue all conditions;
- choose one ROI or generate plots for all defined ROIs; and
- overlay two different conditions on the same plot.

Each curve is the participant-average SNR spectrum for that condition and ROI.

## Multi-Group Projects

When the active `project.json` defines multiple groups and the canonical project
Excel root is selected, Group Options become available. Multi-group plotting is
a one-condition group-overlay workflow:

- choose one condition;
- choose one or more project groups; and
- enable the group overlay to draw a separate participant-average curve for
  each selected group.

Group membership comes from the participant metadata in `project.json`, not
from output-folder names. Workbooks for a multi-group project may be nested as
`<Excel Root>/<Condition>/<Group>/<Workbook>`, but a workbook without a matching
project participant assignment is omitted from the group curves and reported in
the log.

Condition A/B overlay is hidden in multi-group mode because group overlay is the
supported comparison for that mode. The first and second color and legend
controls map to the first two selected groups.

## Figure Options

You can set the title, legend labels, axis labels, axis limits, colors, and the
frequency range read from each workbook. Optional spectral quality-control
checks can write a report of suspicious electrode-level spectra without
silently changing the plotted source values.

## Outputs

The tool writes matching 600-DPI `.png` and `.pdf` files for every generated
condition × ROI figure. The default filename is `<condition> - <ROI>`. A run
summary reports generated files, skipped items, and quality-control reports.

SNR is a descriptive frequency-domain normalization. A peak can help show that
the target response stands above neighboring frequencies, but it is not by
itself an inferential significance test.

## Basic Steps

1. Open **SNR Plots** after processing the project.
2. Confirm the Excel input and figure output folders.
3. Select the condition and ROI scope.
4. For a single-group project, optionally enable a two-condition overlay.
5. For a multi-group project, select groups and enable the group overlay.
6. Adjust labels, ranges, colors, and optional spectral QC.
7. Generate and review the matching PNG/PDF figures and run log.

## References

- Volfart, A., et al. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- Hauk, O., et al. (2021). [Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*, 118460.
- [SNR Plots implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Plot_Generator).
