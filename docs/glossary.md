# Glossary

This glossary explains common FPVS Toolbox terms in plain language.

## `.bdf` file

A BioSemi EEG recording file. This is the main raw data format used by the FPVS
Toolbox processing pipeline.

## Amplitude

The size of the EEG response at a frequency. Larger amplitude means a stronger
measured response at that frequency.

## Baseline

A comparison level used to decide whether a response is above nearby noise or
above a no-response reference point.

## BCA (Baseline-Corrected Amplitude)

Amplitude at a target frequency after subtracting a local noise estimate. BCA is
useful because it focuses on the part of the response that rises above nearby
background activity.

## Base frequency

The main visual stimulation rate. For example, if images appear 6 times per
second, the base frequency is 6 Hz.

## Condition

An experimental category or task event, such as `Faces`, `Objects`, `Semantic`,
or `Color`. In the Toolbox, each condition is linked to one or more trigger
codes.

## Epoch

A time window cut out of the continuous EEG recording around an event. Epochs
are averaged together to estimate the response for a condition.

## Event

A marker in the EEG file showing when something happened in the task, such as a
stimulus appearing. Events are usually identified by trigger codes.

## Event map

The table that connects condition names to trigger codes. If the event map is
wrong, the Toolbox may not find the expected condition data.

## FFT

Fast Fourier Transform. A mathematical step that converts EEG from a time-based
signal into frequency-based values.

In plain language, FFT answers: "How much response is present at each
frequency?"

## Frequency

How often something repeats per second, measured in Hertz (Hz). A 6 Hz response
repeats 6 times per second.

## FullSNR

An exported Excel sheet that stores SNR values across a wider frequency range,
not only the selected target frequencies. It is useful for plotting and checking
the surrounding spectrum.

## Harmonic

A whole-number multiple of a frequency. If the oddball frequency is 1.2 Hz, then
2.4 Hz, 3.6 Hz, and 4.8 Hz are harmonics.

## Mixed model

A statistical model that can handle repeated measurements and some missing data
more flexibly than RM-ANOVA. In FPVS Toolbox, mixed models are often used to
test condition and ROI effects while accounting for repeated observations from
the same participant.

## Oddball frequency

The frequency of the important repeating event in an FPVS design. For example,
if every fifth image is a target and images appear at 6 Hz, the oddball
frequency is 1.2 Hz.

## Participant ID

The label used to identify one participant in exported files and statistics.
Consistent participant IDs are important for grouping data correctly.

## Post-hoc test

A follow-up test used after a larger statistical test suggests an effect. It
helps answer questions such as: "Which condition pair is different within this
ROI?"

## Project root

The main folder where FPVS Toolbox stores project settings and outputs. Use a
local folder rather than a cloud-synced folder while processing.

## QC (Quality Control)

Checks used to find unusual values, missing data, or participants that may need
review before final reporting.

## ROI (Region of Interest)

A named group of electrodes used for averaging and statistics. For example, an
occipito-temporal ROI might include electrodes near the back and side of the
head.

## RM-ANOVA

Repeated-measures ANOVA. A statistical test for within-participant designs. It
works best when every included participant has data for all required conditions
and ROIs.

## SNR (Signal-to-Noise Ratio)

The response at a target frequency divided by nearby noise. Higher SNR means the
response stands out more clearly from the local background.

## Stim channel

The EEG channel that stores trigger/event information. If the stim channel is
set incorrectly, events may not be detected.

## Summed BCA

The primary response value used in many FPVS Toolbox statistics workflows. It is
computed by summing BCA across selected oddball harmonics and averaging across
the electrodes in an ROI.

## Trigger code

A number sent by the experiment software and saved in the EEG file. The Toolbox
uses trigger codes to identify conditions.

## Z score

A standardized measure of how far the target-frequency response is above local
noise. Larger positive Z scores indicate stronger evidence that the response is
above nearby noise.
