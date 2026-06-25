# SNR Plot Generator

The SNR Plot Generator helps you quickly create signal-to-noise ratio (SNR) plots from data that has already been processed in FPVS Toolbox.

Use this tool when you want a fast visual summary of the FPVS response across the conditions and regions of interest (ROIs) in your experiment. Instead of building plots by hand, you select your processed Excel output folder, choose the conditions and ROIs to include, and let FPVS Toolbox generate the figures.

SNR plots are commonly used in FPVS publications because they show how clearly the response at a frequency stands out from the surrounding noise.

## Before You Start

Use the SNR Plot Generator after you have processed your `.bdf` files in FPVS Toolbox and the Toolbox has created Excel output files for each condition.

You should already have:

- a completed FPVS Toolbox project;
- processed Excel output files for your conditions;
- ROIs defined in the Toolbox settings.

## What You Can Do

Use this tool to:

- inspect the SNR response for each condition;
- generate one plot for each ROI;
- compare two conditions on the same figure;
- create high-resolution figure files for reports, presentations, or manuscripts.

For example, if your project has five conditions and four ROIs, the tool can generate SNR plots for each condition and ROI combination.

## Inputs

The tool reads the processed Excel files created by FPVS Toolbox. These files are organized by condition inside your project output folders.

The tool also uses the ROI definitions saved in your Toolbox settings, so you do not need to manually select electrodes for each plot.

## Plot Options

Before generating plots, you can customize:

- plot title;
- legend title and labels;
- x-axis and y-axis labels;
- x-axis and y-axis limits;
- condition colors;
- whether two conditions are overlaid on the same plot.

These settings let you make quick review plots or cleaner figures for sharing with collaborators or for publication.

## Outputs

The SNR Plot Generator saves matching high-resolution `.png` and `.pdf` files for each generated plot.

The `.png` files are useful for slides, posters, and quick sharing. The `.pdf` files are useful when you need a figure format that can be edited or placed into a manuscript layout.

## Basic Steps

1. Process your data in FPVS Toolbox first.
2. Open the SNR Plot Generator.
3. Choose the processed Excel output folder if it is not already selected.
4. Select the conditions and ROIs you want to plot.
5. Adjust titles, labels, axis limits, and colors if needed.
6. Generate the plots.
7. Review the saved `.png` and `.pdf` files.

## References

- David et al. (2025): example FPVS SNR plots.
- Volfart et al. (2021): example FPVS SNR plots.
- Stothart et al. (2021): example FPVS SNR plots.
