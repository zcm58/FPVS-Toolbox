# FPVS Toolbox

FPVS Toolbox is a Windows desktop application for processing and analyzing EEG
data from Fast Periodic Visual Stimulation (FPVS) oddball experiments recorded
with BioSemi systems.

The toolbox implements published FPVS processing methods in an approachable
graphical interface. Its workflow covers project setup, preprocessing,
frequency-domain measures, statistical analysis, and publication-oriented
visualization.

FPVS Toolbox is currently beta software, and features are subject to change.
It is under active development and is used and tested daily.

FPVS Toolbox is open-source software under the MIT License. This repository
contains its application source and development history, with Windows
installers and release notes on its
[Releases page](https://github.com/zcm58/FPVS-Toolbox/releases).
Version 3 update checks use this public repository without requiring a GitHub
account. Version 2.1.2 still checks the previous repository, so the first upgrade
to v3 requires a manual full-installer download. That installation establishes
the separate Update & Repair application and its file inventory.
Previously published assets in
[FPVS-Toolbox-Releases](https://github.com/zcm58/FPVS-Toolbox-Releases/releases)
remain available as historical downloads.

## Features

- Parallel workflows for processing large FPVS-oddball datasets
- Automated batch preprocessing: referencing, filtering, resampling,
  reviewed kurtosis-based channel screening, and authorized channel interpolation
- Epoch extraction and frequency-domain metrics, including FFT amplitude,
  signal-to-noise ratio (SNR), baseline-corrected amplitude (BCA), and z-scores
- Structured long- and wide-format outputs for statistical analysis
- Built-in tools for SNR plots, scalp maps, sequence diagrams, and other
  publication-oriented figures
- Experimental source visualization in the separate LORETA Visualizer beta tool

## Installation

A standalone .exe Windows installer is provided with each release.

1. Download the installer from the
   [Releases page](https://github.com/zcm58/FPVS-Toolbox/releases).
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is 
from an unverified developer.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an installation location.

## License

FPVS Toolbox is released under the MIT License. See [LICENSE](LICENSE) for the
full terms.
