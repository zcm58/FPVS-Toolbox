# Epoch Averaging

Epoch Averaging is the FPVS Toolbox tool for combining preprocessed epochs before post-processing. This could be useful
if you have two or more FPVS conditions designed to measure the same type of

## What It Does

Use this page to document how the tool combines epochs from multiple preprocessed files and how the selected averaging
option affects the result.

## When To Use It

Use Epoch Averaging after preprocessing and before downstream post-processing when multiple preprocessed files should
contribute to a single averaged response.

## Basic Inputs

- Preprocessed epoch files from an FPVS Toolbox workflow.
- The intended averaging method.

## Basic Outputs

- Averaged data files for downstream FPVS Toolbox processing.

## Notes To Fill In

- Explain the difference between pooled averaging and average-of-averages.
- Note which method is preferred for the intended workflow.
- Add any reporting language you want users to copy into methods sections.

## References

- Method references: Add during the manual content pass.
- Toolbox implementation reference: [src/Tools/Average_Preprocessing](https://github.com/zcm58/FPVS-Toolbox-Repo/tree/main/src/Tools/Average_Preprocessing).
