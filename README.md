# FPVS Toolbox

The FPVS Toolbox is a graphical application for preprocessing, analyzing, and visualizing EEG data collected with the Fast Periodic Visual Stimulation (FPVS) paradigm on BioSemi systems. It combines automated cleaning routines, statistical analysis tools, and convenient utilities like image resizing in a single package.

## Features

- Batch processing of BioSemi `.BDF` and `.SET` data files
- Automated preprocessing pipeline: referencing, filtering, resampling, kurtosis-based channel rejection and interpolation
- Extraction of epochs and post-processing metrics (FFT, SNR, BCA, Z-score)
- Statistical analysis window with repeated measures ANOVA and per-harmonic significance testing
- Publication-quality figure generation and optional 3D brain heatmaps
- Image Resizer utility for preparing stimulus assets for PsychoPy experiments
- Averaging utility for combining epochs across files prior to post‑processing
- Built-in update checker that downloads new releases from GitHub

## Installation

Prebuilt installers are provided on the GitHub Releases page. Each release contains a file named `FPVS_Toolbox_<version>-Setup.exe` created with Inno Setup.

1. Download the installer from the Releases page.
2. Double-click the `.exe` file. Because the installer is unsigned, Windows SmartScreen may warn that the app is unrecognized.
3. Choose **More info** and then **Run anyway** to continue.
4. Follow the prompts to select an install location. The installer places `FPVS_Toolbox.exe` and required libraries in the target folder.

Always verify that you obtained the installer directly from this repository's Releases page before bypassing SmartScreen.

### Running from Source

The application can also be launched from source on Windows, macOS, or Linux. Clone the repository and ensure you have Python 3.9+ with the following packages installed:

- `mne`
- `numpy`
- `pandas`
- `scipy`
- `customtkinter`
- `statsmodels` (for statistical analyses)

After installing the dependencies, start the GUI with:

```bash
python src/main.py
```

### Building the Windows Executable

A helper script in `src/Misc/Compiler Script.py` demonstrates the PyInstaller command used to package the toolbox. It collects all required modules and bundles them as a single executable. Adjust paths as needed and run the script to generate your own installer.

## Configuration and Settings

User preferences are stored in `settings.ini` (generated automatically in a configuration folder such as `%APPDATA%\FPVS_Toolbox`). You can adjust appearance mode, default paths, event labels/IDs, and analysis parameters from the Settings window in the application.

Several GUI dimensions are defined in `config.py` if you need to tweak control sizes:

- `BUTTON_WIDTH`
- `ADV_ENTRY_WIDTH`
- `ADV_LABEL_ID_ENTRY_WIDTH`
- `ADV_ID_ENTRY_WIDTH`

## Repository Layout

```
src/                 Main application package
    fpvs_app.py      Core GUI application
    main.py          Entry point for running the toolbox
    Main_App/        Modularized GUI and processing code
    Tools/           Additional utilities (Image Resizer, Stats, Averaging)
    config.py        Global configuration constants
    settings.ini     Default settings file
```

## License

This repository is released under a proprietary license. Viewing the source is permitted for personal or educational purposes only. See [LICENSE](LICENSE) for the full terms.

## Support

If you encounter issues or have feature requests, please open an issue on the GitHub project page. Contributions are welcome, but please respect the modular structure and guidelines noted in the `AGENTS.md` files when proposing changes.
