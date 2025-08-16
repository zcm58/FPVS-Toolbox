# FPVS Toolbox

The FPVS Toolbox is a python based application for preprocessing, cleaning, and analyzing EEG data collected from Fast Periodic Visual Stimulation (FPVS) oddball paradigm experiments on BioSemi systems. The purpose of this project is to standardize data processing and analysis for FPVS experiments and to reduce data analysis times. 

## Features

- Batch processing of BioSemi `.BDF` data files
- Automated preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection and channel interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Built in Statistical analysis tool with repeated-measures ANOVA, linear mixed-effects models, and post-hoc pairwise tests to check for significant FPVS oddball responses. 
- Averaging utility for combining epochs across files prior to post‑processing (useful if one needs to combine two similar FPVS experiments prior to calculating BCA)


## Features currently under development:

- sLORETA source localization and visualization


## Installation

Prebuilt installers are provided on the GitHub Releases page. 

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, Windows SmartScreen may warn that the app is unrecognized.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer places `FPVS_Toolbox.exe` and required libraries in the target folder.

Please verify that you obtained the installer directly from this repository's Releases page before bypassing SmartScreen.


## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational purposes only. See [LICENSE](LICENSE) for the full terms.

## Support

If you encounter issues or have feature requests, please open an issue on the GitHub project page. 
