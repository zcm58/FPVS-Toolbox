# FPVS Toolbox

FPVS Toolbox is a Windows desktop application for preprocessing, cleaning, and analyzing EEG data collected from Fast Periodic Visual Stimulation (FPVS) oddball paradigm experiments on BioSemi systems.

## Features

- Automated batch preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection, and channel interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Built-in statistical analysis with repeated-measures ANOVA, linear mixed-effects models, and post-hoc pairwise tests
- Support for single-group and multi-group FPVS datasets


## Removed Features

- LORETA/eLORETA source localization and 3D visualization were removed from the active app. Restoring them would require a new explicitly scoped feature with fresh architecture, tests, and verification.


## Installation

A prebuilt Windows installer is provided with every release.

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is from an unverified developer.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer places `FPVS_Toolbox.exe` and required libraries in the target folder.

Please verify that you obtained the installer directly from this repository's Releases page before bypassing any anti-virus flags.

## Documentation

- User documentation lives in [`docs/`](docs/).
- Developer setup and verification notes live in [`docs/development.md`](docs/development.md).
- Agent-facing repo guidance lives in [`AGENTS.md`](AGENTS.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational purposes only. See [LICENSE](LICENSE) for the full terms.
