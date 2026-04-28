# FPVS Concepts for Non-Experts

Use this page when FPVS, oddball responses, harmonics, BCA, SNR, or ROI terms are unfamiliar.

This page explains the main FPVS terms used in the app and docs. It is written for readers who are comfortable with basic data analysis but are new to EEG.

## FPVS in one sentence

FPVS presents images at a fixed rhythm and uses EEG to test whether the brain locks onto that same rhythm - and onto any slower rhythm created by periodic "oddball" images.

> **Mental model:** show the visual system a rhythm, then look for that rhythm in the EEG.

## Core ideas

### Base frequency

The **base frequency** is the overall image presentation rate.

- **Example:** 6 Hz means 6 images are shown each second.
- **What it captures:** the brain's general response to the visual stream.

In FPVS, this is the fast repeating rhythm that structures the whole sequence.

### Oddball frequency

An **oddball** is the item that breaks the repeating pattern. The **oddball frequency** is the rate at which that special item appears.

- **Example:** if images are shown at 6 Hz and every 5th image is an oddball, the oddball frequency is **6/5 = 1.2 Hz**.
- **What it captures:** whether the brain is responding differently to the oddball than to the base stream.

A peak at the oddball frequency means there is a **stimulus-locked difference** between base and oddball processing. By itself, it does **not** tell you exactly *why* the difference happened - only that it happened. This is why careful design of the experiment is important.

### Harmonics

A **harmonic** is an integer multiple of a frequency.

- **Fundamental frequency:** the main frequency itself
- **Harmonics:** 2x, 3x, 4x, and so on

**Example:** if the oddball frequency is 1.2 Hz, its harmonics are 2.4 Hz, 3.6 Hz, 4.8 Hz, and so on.

Why do harmonics appear? Because brain responses are usually **not perfect sine waves**. When the response has a more complex shape, some of its energy spreads into multiples of the main frequency.

In practice, FPVS analyses often look at the oddball frequency **plus several harmonics**, because the clearest evidence is often spread across them. If one of those harmonics overlaps with the base frequency, it is often excluded from the oddball measurement.

### FFT

The **Fast Fourier Transform (FFT)** converts EEG from the **time domain** to the **frequency domain**.

- **Time domain:** voltage changing over time
- **Frequency domain:** how strongly each frequency is present in the signal

In FPVS, the FFT is what turns a long EEG trace into a spectrum with peaks at expected frequencies.

A useful way to think about it: the FFT does not decide what the brain "means." It reorganizes the data so stimulus-locked rhythms are easy to measure.

### BCA, SNR, and Z score

These are three common ways to describe the same frequency-domain peak.

- **BCA (baseline-corrected amplitude):** the peak amplitude after subtracting nearby background activity. Usually reported in **microvolts (uV)**.
- **SNR (signal-to-noise ratio):** the peak amplitude relative to nearby noise.
- **Z score:** how unusual the peak is compared with nearby noise bins.

**What "nearby noise" means:** in FPVS, researchers usually estimate background EEG noise from frequencies just to the left and right of the frequency of interest.

A useful shorthand is:

- **BCA** = *What is the net amplitude of the response after removing the noise?*
- **SNR** = *How clearly does the response stand out from nearby noise?*
- **Z score** = *How statistically unusual is the response compared with nearby noise?*

These measures are related, but they answer slightly different questions. BCA is useful for **effect size**, SNR is useful for **signal clarity**, and Z score is useful for **detectability**.

## Why this matters for analysis

FPVS is useful because it turns a broad question -

**"Did the brain respond differently?"**

into a more concrete question -

**"Is there a measurable peak at a frequency where we expected one?"**

That makes the analysis pipeline easier to follow:

1. Present images at a known base rate.
2. Insert oddballs at a known slower rate.
3. Use the FFT to convert EEG into a frequency spectrum.
4. Measure peaks at the base frequency, oddball frequency, and selected harmonics.
5. Compare those measurements across conditions, ROIs, or groups.

> **ROI** stands for **region of interest**. In EEG, this usually means a small set of electrodes grouped together because a response is expected there.

## Continue learning

- [Feature Tour](feature-tour.md)
- [Processing Pipeline Overview](processing-pipeline.md)
- [Statistical Analysis Overview](statistical-analysis.md)
