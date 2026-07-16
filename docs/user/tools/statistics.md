# Statistical Analysis

Statistical Analysis turns processed FPVS condition workbooks into a common
Summed BCA dependent variable, runs the supported single-group analyses, and
exports reviewable results.

## When To Use It

Use this tool after preprocessing and post-processing have created one Excel
workbook per participant and condition under the project's `1 - Excel Data
Files` folder. Select at least two conditions and confirm that the project ROIs
match the analysis plan before running statistics.

## Inputs and Participant Review

The tool reads the processed workbooks, the active project settings, and the ROI
definitions saved in Settings. Before a run, you can:

- choose the conditions included in the analysis;
- review the participants found across those conditions;
- apply manual participant exclusions; and
- review quality-control and non-finite/outlier flags.

The full in-app statistical pipeline is currently limited to single-group
projects. In a multi-group project, use **Export Stats-Ready Workbook** and run
group comparisons in external statistical software.

## Summed BCA and Harmonic Selection

The default policy determines one common list of oddball harmonics from the
grand-averaged `FullFFT Amplitude (uV)` spectra. Detection uses the union of the
electrodes in the project's predefined ROIs and a strict `z > 1.64` threshold.
Base-rate overlaps are excluded.

For each candidate harmonic, the noise window spans ±10 FFT bins around the
target. The target bin and its immediately adjacent bins are excluded, then the
single lowest and single highest finite noise values are removed before the
mean and population standard deviation are calculated.

Summed BCA then includes every eligible non-base oddball harmonic through the
highest detected significant harmonic, even if an intervening harmonic was not
itself significant. A one-pass gap guard prevents a lone high-frequency peak
from filling a very long empty interval: if more than 10 eligible non-base
harmonics lie strictly between the two highest detected significant peaks, the
highest peak and all harmonics above the next-highest peak are excluded from
summation. Base-rate overlaps do not count toward the gap, and exactly 10
intervening eligible harmonics remains allowed. The excluded upper peak remains
listed as detected for transparency. The same included list is applied to every
participant, condition, and ROI. The alternate “significant harmonics only”
method is unchanged, and a fixed predefined list remains available when the
study protocol requires one.

The processing workflow records the selection in
`Quality Check/Harmonic_Selection_Summary.xlsx`, including the harmonics that
passed the threshold and those included in the final sum.

## Supported Analyses

**Analyze Single Group** runs the current pipeline:

- repeated-measures ANOVA across selected conditions and ROIs;
- a linear mixed-effects model;
- interaction follow-up comparisons with multiplicity correction; and
- condition-by-ROI baseline-versus-zero tests.

The **Advanced** menu can run or export individual pipeline steps. These tools
do not replace an analysis plan: check model assumptions, coding, exclusions,
and multiplicity choices before reporting results.

## Outputs

Statistical result workbooks, text reports, reporting summaries, and participant
flagging records are written under `3 - Statistical Analysis Results` in the
active project.

**Export Stats-Ready Workbook** writes `Stats_Ready_Summed_BCA.xlsx` with:

- `Long_Format`: one subject × group × condition × ROI row per observation;
- `Wide_Format`: one row per subject for repeated-measures software;
- `Selection_Summary`: the active harmonic policy and included list; and
- `Harmonic_Selection`: the per-harmonic detection evidence.

Use the stats-ready export for JASP, R/RStudio, SAS, or another external package,
especially when a project contains multiple groups or needs a model not offered
by the in-app pipeline.

## References

- Volfart, A., et al. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- Rossion, B., Retter, T. L., & Liu-Shuang, J. (2020). [Understanding human individuation of unfamiliar faces with oddball fast periodic visual stimulation and electroencephalography](https://doi.org/10.1111/ejn.14865). *European Journal of Neuroscience, 52*(10), 4283–4344.
- See [Methods and References](../reference/index.md) for the broader FPVS method list.
- [Statistical Analysis implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Stats).
