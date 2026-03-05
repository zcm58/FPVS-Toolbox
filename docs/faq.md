# FAQ

## Which file format is supported for processing?

The main pipeline currently supports BioSemi `.bdf` files.

## Can I use cloud folders for my project root?

Local disk folders are recommended. Cloud sync folders can cause file lock or path timing issues during exports.

## Do I need coding experience?

No. The standard FPVS processing and statistics workflows are GUI-based.

## What does "Summed BCA" mean?

It is the ROI-level dependent variable used in stats. BCA is summed across selected oddball harmonics and then averaged across ROI electrodes.

## Why am I missing condition results for a participant?

Usually because no events were found for that condition code or there were no valid epochs after epoching.

## Where are my output files?

See [Output Files](outputs-reference.md) for the default folder structure and expected exports.

## What should I report in manuscripts?

Use the checklists in [Processing Pipeline Overview](processing-pipeline.md) and [Statistical Analysis Overview](statistical-analysis.md), and save your settings plus exported tables.
