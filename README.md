![Snake animation](https://github.com/zcm58/zcm58/blob/output/github-contribution-grid-snake.svg)

# FPVS Toolbox

The FPVS Toolbox is a python based application for preprocessing, cleaning, and analyzing EEG data collected from Fast Periodic Visual Stimulation (FPVS) oddball paradigm experiments on BioSemi systems. The purpose of this project is to reduce the time needed to analyze data and to standardize an analysis pipeline. 

## Features

- Batch processing of BioSemi `.BDF` data files
- Automated preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection and channel interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Built in Statistical analysis tool with repeated-measures ANOVA, linear mixed-effects models, and post-hoc pairwise tests to check for significant FPVS oddball responses. 


## Features currently under development:

- LORETA source localization and 3D visualization of neural responses on a transparent brain mesh


## Installation

A prebuilt installer is provided with every release. 

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, anti-virus software may warn you that the app is from an unverified developer. You'll need to manually bypass this warning. 
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer places `FPVS_Toolbox.exe` and required libraries in the target folder.

Please verify that you obtained the installer directly from this repository's Releases page before bypassing any anti-virus flags.


## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational purposes only. See [LICENSE](LICENSE) for the full terms.
