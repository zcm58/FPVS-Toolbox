# FPVS Toolbox Documentation

This site is the short public reference for FPVS Toolbox. It is intentionally limited to basic use notes, tool entry points, and reference links.

Detailed FPVS theory, methods explanations, and advanced conceptual material should live in the separate FPVS concepts site.

## Key Features and Assumptions

### FPVS Toolbox Project Root

FPVS Toolbox uses a project root folder to organize work. Every new project creates a new folder inside that root folder, and future project outputs should stay inside the project folder created for that study.

Use the project root as the top-level home for all FPVS Toolbox projects, not as a folder for loose analysis files.

### Data Compatibility

FPVS Toolbox currently supports BioSemi 10-10 montage 64-electrode data.

Other electrode layouts, recording systems, or custom montages are not currently part of the supported public workflow unless they are converted to match the expected BioSemi 64-electrode structure.

### Experiment Assumptions

FPVS Toolbox assumes trigger codes are defined on a per-condition basis before analysis, typically in PsychoPy or FPVS Studio.

When creating a project, the condition settings in FPVS Toolbox should match the trigger codes used during data collection.

## Tool Pages

Each tool page is a scaffold for short practical notes and a references section:

- [Epoch Averaging](tools/epoch-averaging.md)
- [SNR Plot Generator](tools/snr-plot-generator.md)
- [Publication Maps / Scalp Maps](tools/publication-maps.md)
- [Statistics](tools/statistics.md)
- [Ratio Calculator](tools/ratio-calculator.md)
- [Sequence Figure](tools/sequence-figure.md)
- [Image Resizer](tools/image-resizer.md)
- [Individual-Level Detectability](tools/individual-level-detectability.md)
- [Publication Report](tools/publication-report.md)
- [LORETA Visualizer](tools/loreta-visualizer.md)

## Reference Links

Use [Reference Links](reference/index.md) for repository links, release links, citation placeholders, and other lightweight references.
