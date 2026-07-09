# Epoch Averaging

Epoch Averaging is a beta tool that combines selected event epochs before the
usual FFT, SNR, BCA, and z-score calculations. Unlike its earlier documentation,
the active workflow starts from raw BioSemi `.bdf` files; it does not take
preprocessed epoch files as input.

## When To Use It

Use this tool only when multiple event IDs are scientifically justified as
measurements of the same response and should form one derived condition. Decide
and document that grouping before inspecting the result whenever possible.

The tool uses the active project's preprocessing and epoch settings, so confirm
the reference, filter, sampling, trigger, and epoch-window settings in the main
application first.

## Inputs and Group Setup

Epoch Averaging automatically lists raw `.bdf` files from the active project's
data folder. You can add or remove BDF files, then create one or more averaging
groups. For each group, provide:

- a descriptive output name;
- the integer event IDs to combine; and
- an averaging method.

The event IDs are applied to every selected BDF file. Files are loaded and
preprocessed in the background using the active main-app settings before epochs
are created.

## Averaging Methods

**Pool Trials** concatenates all eligible epochs for the selected event IDs and
then averages them. Conditions with more accepted trials therefore contribute
more weight. This is the default.

**Average of Averages** first averages each event-ID epoch set and then takes an
equal-weight grand average of those evoked responses. Each available event set
therefore contributes equally regardless of trial count.

The two methods answer different weighting questions. Record which method was
used and review the accepted trial counts before interpreting a derived
condition.

## Outputs

For each participant and averaging-group recipe, the combined time-domain
response is passed through the normal FPVS post-processing stage. The tool
writes the resulting standard frequency-domain outputs to the project's
configured results folder for downstream plotting or statistics.

Epoch Averaging does not change the original BDF files. Stop requests are
handled between processing steps, so the current file or step may finish before
the run stops.

## Interpretation

Do not combine conditions solely to increase signal strength. Pooling can hide
real condition differences, and Average of Averages can over-weight a condition
with relatively few accepted trials. Keep the original conditions and the
derived grouping rule auditable in the study methods.

## References

- [MNE-Python `concatenate_epochs` documentation](https://mne.tools/stable/generated/mne.concatenate_epochs.html).
- [MNE-Python `grand_average` documentation](https://mne.tools/stable/generated/mne.grand_average.html).
- [Epoch Averaging implementation](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Average_Preprocessing).
