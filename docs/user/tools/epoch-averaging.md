# Epoch Averaging

Use this page when you need to combine preprocessed epochs before
post-processing.

Epoch Averaging opens from the main app sidebar as **Epoch Averaging** and from
the Tools menu as **Average Epochs in Pre-Processing Phase**. It is intended for
workflows where multiple preprocessed files should contribute to one averaged
response before the regular post-processing outputs are generated.

## When to use it

Use this tool only after preprocessing has produced files that are ready to be
combined.

The tool supports two averaging ideas:

- **Pooled Average:** combines all epochs into one pool before averaging. This
  gives equal weight to each epoch.
- **Average of Averages:** averages each file first, then averages those file
  averages together. This gives equal weight to each file.

## Output

The output can be used as the averaged input for downstream FPVS processing
steps. Record which averaging method you used because the weighting differs
between the two modes.

