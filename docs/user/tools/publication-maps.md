# Scalp Maps

Scalp Maps exports grand-average sensor-space topographies from processed FPVS
workbooks. It supports baseline-corrected amplitude (BCA), signal-to-noise ratio
(SNR), and summed-harmonic z-score maps.

Scalp Maps is currently a beta tool. Enable **Beta Tools** in
**Settings > Advanced**, close and reopen FPVS Toolbox, then choose **Scalp
Maps** from the Beta Tools section. The shared beta notice appears before the
tool first opens in each app session.

## When To Use It

Use Scalp Maps after the selected conditions have been processed and the
project's ROI and frequency settings are final. The tool reads the active
project's Excel results by default and writes to `4 - Scalp Maps` under the
project results folder unless you choose another location.

## Inputs

Select one or more processed conditions, the metrics to draw, and the output
folder. In a multi-group project, select one group or choose all groups to
create a separate output set for each group. In a project with exactly two
canonical groups, you can instead select one condition and export a descriptive
side-by-side group comparison. Each group is averaged independently; groups are
never pooled into one map. Scalp Maps loads the project-wide
significant-harmonic list that FPVS
Toolbox saved when processing completed. Selecting fewer conditions or applying
display exclusions does not recalculate or replace that list.

If the saved selection is missing or no longer matches the processed
workbooks, project settings, ROIs, or frequency-domain QC state, Scalp Maps
stops and asks you to reprocess the project or recalculate harmonic selection
from Settings. It never silently creates a tool-specific harmonic list.

The source workbooks must contain exact `"{frequency:.4f}_Hz"` columns in the
relevant sheets:

- `BCA (uV)` for BCA maps;
- `SNR` for SNR maps; and
- `Z Score` for z-score maps.

Workbooks missing exact selected columns are reported rather than matched to a
nearby frequency. An unreadable active workbook or a missing requested sheet,
electrode column, or exact harmonic column stops that requested run; the tool
does not silently publish a reduced participant cohort.

## How Values Are Combined

- BCA values are summed across the selected harmonics for each participant and
  electrode, then averaged across participants.
- SNR values are averaged across the selected harmonics for each participant
  and electrode, then averaged across participants.
- Z-scores are combined as `sum(z) / sqrt(K)`, where `K` is the number of
  selected harmonics, then averaged across participants.

Project participant, participant-condition, and frequency-domain participant
and electrode exclusions are applied before aggregation. Canonical participant
and group identity comes from `project.json` through the shared processed-data
index, not from filenames or folder names.

## Figure Options

You can export individual condition maps, a paired condition figure, or—when
the project has exactly two canonical groups—a two-group comparison for one
condition. In either comparison mode, selected metrics are arranged as rows,
the conditions or groups are columns, and both columns share a color scale for
each metric. The group comparison is descriptive: it is not a between-group
statistical test or a difference map.

For a project with canonical repeated-session metadata, the **Compare**
selector adds two safe workflows:

- **Condition (one session)** runs the existing condition, paired-condition,
  and group options within one explicitly selected visit.
- **Session comparison** selects one task condition and two sessions. It
  creates a group-column × session-row grid for the project's two stable
  groups, with one shared color scale across all four maps for each metric.

Every panel title uses the canonical session label without visit numbers or
sample-size annotations. The optional paired-difference row is calculated as
comparison minus reference within each participant before averaging; its
diverging color scale is shared across groups. Participant and paired counts
remain part of the internal aggregation checks but are not printed on the
figure. Missing `recording_id`, `session_id`, `group_id`, or visit metadata
blocks the run, and Scalp Maps never guesses identity from paths or filenames.

BCA and SNR can use fixed or automatic color limits. The initial fixed ranges
are 0.0–0.4 µV for BCA and 1.0–1.5 for SNR. Z-score maps use a configurable
lower display threshold of 1.64 by default; values below the display threshold
are white.

Rendered BCA maps clip negative values to the low end of the color scale.

## Outputs

The tool writes matching 600-DPI `.png` and `.pdf` figures only. Ordinary
multi-group runs give each group its own canonical output folder. Two-group
comparison mode instead writes the comparison figure directly in the selected
`4 - Scalp Maps` folder. Scalp Maps does not create source-data workbooks or
other auxiliary output files.

Repeated-session grids are also written directly in the selected base folder,
using a `_session_grid` filename suffix. Their complete PNG/PDF set is staged
and published transactionally with the same cancellation guarantees.

Generation is transactional: cancelling or encountering an error does not
publish a partial figure pair. The Generate action and project navigation
remain locked until the active worker has actually stopped.

Scalp topographies interpolate measurements across electrodes. Missing or
non-finite sensors are omitted rather than converted to zero, and a map is
blocked when too few non-collinear sensors remain for stable interpolation.
They show the sensor-space distribution and should not be described as
anatomical source locations.

## References

- Hauk, O., et al. (2021). [Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*, 118460.
- Volfart, A., et al. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- [Scalp Maps implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Publication_Maps).
