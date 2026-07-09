# FPVS Toolbox

FPVS Toolbox is a Windows desktop application for processing and analyzing EEG
data from Fast Periodic Visual Stimulation (FPVS) oddball experiments recorded
with BioSemi systems.

The toolbox implements published FPVS processing methods in an approachable
graphical interface. Its workflow covers project setup, preprocessing,
frequency-domain measures, statistical analysis, and publication-oriented
visualization.

FPVS Toolbox was designed with non-expert users in mind and is actively used in
FPVS-EEG research.

## Features

- Automated batch preprocessing: referencing, filtering, resampling,
  kurtosis-based channel rejection, and channel interpolation
- Epoch extraction and frequency-domain metrics, including FFT amplitude,
  signal-to-noise ratio (SNR), baseline-corrected amplitude (BCA), and z-scores
- Structured Excel outputs for statistical analysis
- Built-in tools for SNR plots, scalp maps, sequence diagrams, and other
  publication-oriented figures

## Installation

A prebuilt Windows installer is provided with each release.

1. Download the installer from the
   [Releases page](https://github.com/zcm58/FPVS-Toolbox-Repo/releases).
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is 
from an unverified developer.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an installation location.

## License

FPVS Toolbox is released under the MIT License. See [LICENSE](LICENSE) for the
full terms.
