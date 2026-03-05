# FPVS Concepts for Non-Experts

This page explains the main FPVS terms used in the app and docs.

## FPVS in one sentence

FPVS presents images at a steady rate, and EEG is analyzed at that same rhythm to detect stimulus-locked brain responses.

## Core ideas

### Base frequency

The base frequency is the main image presentation rate (for example, 6 Hz).

### Oddball frequency

An oddball appears every N images, so its frequency is lower than the base rate. Example: 6 Hz base and every 5th image oddball gives 1.2 Hz oddball.

### Harmonics

If a response exists at 1.2 Hz, it often also appears at multiples of that frequency (2.4, 3.6, 4.8 Hz, and so on).

### FFT

The Fast Fourier Transform converts EEG from time-domain signals into a frequency spectrum so peaks at oddball and harmonic frequencies can be measured.

### BCA, SNR, and Z score

- **BCA**: baseline-corrected amplitude at a target frequency.
- **SNR**: signal amplitude relative to local surrounding noise.
- **Z score**: standardized distance from local noise.

## Why this matters for analysis

- Processing converts raw EEG into stable frequency-domain metrics.
- Statistical analysis then tests whether those metrics differ across conditions, ROIs, or groups.

## Continue learning

- [Feature Tour](feature-tour.md)
- [Processing Pipeline Overview](processing-pipeline.md)
- [Statistical Analysis Overview](statistical-analysis.md)
