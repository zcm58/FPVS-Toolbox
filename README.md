# FPVS Toolbox

FPVS Toolbox is a Windows desktop application that streamlines data processing and analysis of EEG data collected from 
Fast Periodic Visual Stimulation (FPVS) oddball paradigm experiments on BioSemi systems. 

The FPVS Toolbox applies published data processing methods found in the most recent FPVS publications (see David
et al., 2025; Volfart et al., 2021; Hauk et al., 2021; Hauk et al., 2025; Rossion et al., 2020) behind an easy to use
GUI and provides significant speed improvements over comparable MATLAB processing pipelines. 

This package was designed for the non-expert user in mind and is currently being actively used FPVS-EEG research.

## Features

- Automated batch preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection,
and channel interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Data is output in a format ready for statistical analysis 
- Mutliple built-in figure generation tools allow for publication quality figure generation with ease 

## Installation

A prebuilt Windows installer is provided with every release.

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is 
from an unverified developer.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer handles everything from there. 

## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational 
purposes only. See [LICENSE](LICENSE) for the full terms.
