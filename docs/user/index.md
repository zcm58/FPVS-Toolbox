# FPVS Toolbox Documentation

This site includes basic documentation of FPVS Toolbox features and relevant publications supporting the design
of the toolbox.

## Key Features and Assumptions

### FPVS Toolbox Project Root

FPVS Toolbox uses a project root folder design to organize your work. Every new project you create and all associated
output files live inside its own project subfolder within the project root.

### Data Compatibility

FPVS Toolbox currently supports BioSemi 10-10 montage 64-electrode data.

Other electrode layouts, recording systems, or custom montages are not currently supported. Future updates will bring
support for other data formats and will allow for other montages or custom electrode montages.

### Experiment Assumptions

FPVS Toolbox assumes trigger codes are defined on a per-condition basis before analysis, typically in
PsychoPy or FPVS Studio.

When creating a project, the condition settings in FPVS Toolbox should match the trigger codes used during
data collection.

## Tool Pages

See the following sections for more information regarding each tool provided in FPVS Toolbox.

- [Epoch Averaging](tools/epoch-averaging.md)
- [SNR Plot Generator](tools/snr-plot-generator.md)
- [Publication Maps / Scalp Maps](tools/publication-maps.md)
- [Statistics](tools/statistics.md)
- [Ratio Calculator](tools/ratio-calculator.md)
- [Sequence Figure](tools/sequence-figure.md)
- [Individual-Level Detectability](tools/individual-level-detectability.md)
- [Publication Report](tools/publication-report.md)
- [LORETA Visualizer](tools/loreta-visualizer.md)
