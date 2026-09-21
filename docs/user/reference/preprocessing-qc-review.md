# Inspecting preprocessing QC evidence

The seven preprocessing QC steps retain their existing order. Background
source loading begins with step 2. A clean summary still waits for Continue;
there is no timed delay or requirement to wait for preloading to finish.

## Marker timing review

If oddball triggers differ by condition, open **Settings > Protocol**, enable
**Use a different oddball marker for each condition**, and enter every
condition's oddball code in the table. For example, condition onset codes 1–5
can use oddball codes 51–55 respectively. These are distinct from the onset
markers themselves. Save and start a fresh processing run; the previous run's
marker decisions do not apply to the changed schema. The switch applies only
to the active project. Without recording-specific schemas, switching it off
restores the shared marker code.
Expected analyzed cycles and duration remain separate protocol settings.

If trigger conventions changed during data collection, one condition mapping
cannot describe every file. For example, some recordings may use codes 51–55
for conditions 1–5, while later recordings use 55 in every condition. Configure
the assignments explicitly:

1. In **Settings > Protocol**, enter the project condition markers to use as a
   template, such as `1 → 51` through `5 → 55`.
2. Enable **Recording-specific trigger schemas** and open **Configure recording
   schemas…**.
3. For each registered recording, choose **Project condition markers** or
   **Shared marker**, and enter the shared code where applicable. Select
   multiple rows to apply the same choice together. Review the displayed
   assigned markers before applying.
4. Choose **Apply schemas**, then save Settings and start a fresh processing
   run. Applying the dialog alone does not save the project.

Every registered recording needs an explicit assignment. A new recording stays
unassigned until reviewed; the application does not guess its schema from its
filename or automatically switch to whichever trigger code appears. Confirm
assignments using the recording's trigger evidence and acquisition records.
Turning off recording-specific schemas returns to the configured project-wide
condition markers or shared code.

Marker schemas do not change condition-onset codes or combine adjacent blocks.
If one condition appears three times and another only once, investigate that
onset pattern separately. Likewise, the number of recorded oddball markers does
not automatically set the expected analyzed cycle count or duration.

Repeated runs of the same condition are reviewed and cropped separately, then
averaged sample-by-sample in the time domain before the FFT. For example, two
runs analyzed at 144 oddball cycles and 1.2 Hz each produce one 120-second
averaged waveform. Do not double the expected cycle count because a condition
was presented twice. The recorded marker count can exceed the analyzed cycle
count; that alone does not trigger a timing warning.

The project's condition map must include every condition-start code in the
recording. If a start code is omitted, its following oddball markers can be
assigned to the preceding condition, and the pause between conditions can
appear as a missing-marker gap. Confirm the omitted code's meaning against the
acquisition design and correct the condition map before restarting processing.
To leave a known condition out of analysis, retain its start code in the map
and use explicit condition exclusions so its boundaries remain recognizable.

Step 2 shows one flagged repetition at a time: the affected recording, a short
explanation of the marker finding, and the required analysis duration.

- **Use verified window…** chooses a window that passed the marker-spacing
  check. Data outside that window does not enter this repetition's analysis.
- **Keep planned window…** uses the planned window despite the finding. Supply
  independent evidence, such as a presentation log or photodiode trace, that
  stimulation stayed continuous and correctly timed.
- **Exclude this repetition…** leaves only this condition repetition out of
  analysis. The raw file is kept.

Unavailable choices explain why they cannot be used. **Technical details…**
opens the complete marker times and interval evidence without changing a
decision. A marker gap alone does not show that visual stimulation stopped.
**Cancel Processing** stops the request so you can investigate.

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
