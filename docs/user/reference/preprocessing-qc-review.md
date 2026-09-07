# Inspecting preprocessing QC evidence

The seven preprocessing QC steps retain their existing order. Background
source loading begins with step 2. A clean summary still waits for Continue;
there is no timed delay or requirement to wait for preloading to finish.

## Kurtosis review

Select an electrode and choose **Inspect signal**. The overview preserves each
display bin's minimum and maximum, so a short burst cannot disappear simply
because the display picked every nth sample. Occurrences remain separate.
The detail view shows recording-relative seconds, neighboring electrodes and
a shared visible microvolt scale. Click the overview or use Earlier, Later,
the start time and window size to inspect another interval.

Available signal views are:

- **Raw acquisition:** samples before software referencing or filtering.
- **Intended initial reference:** the unfiltered signal after subtracting the
  configured reference pair's mean, for inspection only.
- **Reference comparison:** the selected acquisition channel, its referenced
  counterpart and the reference channels.
- **Prepared before interpolation:** the same prepared samples used for
  kurtosis, when the verified preprocessing checkpoint is available.

The current view's stage is always labeled. Reference comparison does not
change project settings. An unavailable checkpoint or reference is reported
explicitly. Close inspection can cancel a background read.

Select multiple rows to apply **Interpolate** or **Keep channel** to selected
undecided manual flags. **Interpolate all undecided** affects only eligible,
visible undecided manual rows. Both actions preserve previous decisions,
reasons and automatic policies; the affected counts appear beside the actions.
**Undo bulk edit** restores the last bulk edit until another manual edit or
policy change. **Next undecided** includes findings with invalid statistics
that still require individual review. Nothing is saved until Apply decisions.

Interpolation applies to the electrode throughout the processed recording.
The condition count and repair scope remain visible beside the decision.

## Related signal findings and new diagnostic cues

Step 7 groups overlapping review intervals by recording, condition and
occurrence. Select an episode to see all linked evidence or expand it to
inspect individual findings. Searching does not erase evidence linked to a
matching episode. Each original finding remains in the review workbook.

Additional cues use MNE's amplitude-annotation implementation to locate exact
flat segments and abrupt consecutive-sample transitions. Extreme repeated
plateaus receive a candidate-clipping label. **Go to event** opens the raw
interval supporting a listed cue. These cues use provisional settings and
cannot prove an artifact, ADC saturation or a need for interpolation. A
pattern appearing somewhere in every occurrence does not establish continuous
electrode failure. The evidence states its assessed scope and any output or
data limitations. No returned MNE annotations or bad-channel suggestions are
automatically applied.

If these additional diagnostics fail or reach their event display limit,
step 7 reports that explicitly. Missing cues or a shortened list do not mean
the recording is clean. Signal inspection verifies the recording and cached
samples before displaying them; changed files require a fresh QC review.

## Repair support

**Repair support** shows a proposed scenario before applying kurtosis choices.
The selected undecided electrode can be included for inspection. Red points
identify proposed repairs; blue points identify nearby available donors.
Other undecided candidates are withheld as donors. After processing, the
interpolation-burden review offers **Inspect repair support** for the actual
successful repairs and actual retained scalp set.

The signal viewer's optional spatial-support estimate temporarily withholds
usable electrodes from copied, bounded samples and asks MNE interpolation to
predict them. Its reported agreement describes those tested electrodes and
samples only. It cannot establish the unknown true signal at damaged sensors.
Neither donor distances nor prediction errors create an automatic pass/fail
decision. The existing automatic kurtosis policies are unchanged, and the
registry of calibrated corroborating detectors remains empty.
