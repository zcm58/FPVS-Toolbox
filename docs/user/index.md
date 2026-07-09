# FPVS Toolbox Documentation

This site explains the active FPVS Toolbox workflow, its built-in tools, and the
published methods that inform the application.

## Key Features and Assumptions

### FPVS Toolbox Project Root

FPVS Toolbox organizes work under a project root. Each project has its own
subfolder containing the project manifest, source-data location, processed
workbooks, quality-control records, statistical outputs, and figures.

### Data Compatibility

The currently validated workflow targets BioSemi ActiveTwo 64-channel BDF
recordings using the standard BioSemi64 electrode names. Other recording
systems, file formats, channel layouts, or custom montages have not been
validated and may fail or produce incomplete analyses or figures.

### Experiment Assumptions

FPVS Toolbox assumes trigger codes are defined on a per-condition basis before analysis, typically in
PsychoPy or FPVS Studio.

When creating a project, the condition settings in FPVS Toolbox should match the trigger codes used during
data collection.

## Tool Pages

The **Workspace Tools** section of the app sidebar shows these default tools:
Statistical Analysis, SNR Plots, Scalp Maps, LORETA Visualizer, and Sequence
Figure.

Ratio Calculator, Individual Detectability, and Epoch Averaging are beta tools.
To show them, open **Settings > Advanced**, enable **Beta Tools**, then close
and reopen FPVS Toolbox.

See the following sections for more information regarding each tool provided in FPVS Toolbox.

- [Statistical Analysis](tools/statistics.md)
- [SNR Plots](tools/snr-plot-generator.md)
- [Scalp Maps](tools/publication-maps.md)
- [LORETA Visualizer](tools/loreta-visualizer.md)
- [Sequence Figure](tools/sequence-figure.md)
- [Ratio Calculator](tools/ratio-calculator.md)
- [Individual Detectability](tools/individual-level-detectability.md)
- [Epoch Averaging](tools/epoch-averaging.md)
