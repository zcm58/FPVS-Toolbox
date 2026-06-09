# FPVS Toolbox

FPVS Toolbox is a Windows desktop application for preprocessing, cleaning, and analyzing EEG data collected from Fast Periodic Visual Stimulation (FPVS) oddball paradigm experiments on BioSemi systems.

## Features

- Automated batch preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection, and channel interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Built-in statistical analysis with repeated-measures ANOVA, linear mixed-effects models, and post-hoc pairwise tests
- Support for single-group FPVS statistical workflows
- Experimental LORETA Visualizer branch for beta 3D cortical source-map viewing


## Removed Features

- The retired LORETA/eLORETA source-localization implementation was removed from the active app. The current `src/Tools/LORETA_Visualizer/` work is a separate experimental visualization branch with fresh architecture, tests, and documentation; it is not a restoration of the removed implementation.


## Installation

A prebuilt Windows installer is provided with every release.

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is from an unverified developer.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer places `FPVS_Toolbox.exe` and required libraries in the target folder.

Please verify that you obtained the installer directly from this repository's Releases page before bypassing any anti-virus flags.

## Documentation

- User documentation lives in [`docs/user/`](docs/user/).
- Developer setup and verification notes live in [`docs/agent/guides/development.md`](docs/agent/guides/development.md).
- Agent-facing repo guidance lives in [`AGENTS.md`](AGENTS.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational purposes only. See [LICENSE](LICENSE) for the full terms.
