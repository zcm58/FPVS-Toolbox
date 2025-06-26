The FPVS Toolbox is a work-in-progress software solution for use with BioSemi EEG datafiles. Feature highlights include:

- Easy Image Resizing for use with PsychoPy
- Automated data cleaning and post processing
- Automated statistical analysis with the ability to detect significant neural responses to experimental stimuli
- Easy generation of publication quality figures & 3D heatmaps of brain activity
- Automated BCA, SNR, and FFT calcuations

## Versioning

The toolbox version is defined in `config.py` as `FPVS_TOOLBOX_VERSION`. Scripts
that need the version should import this constant rather than hard coding a
string. For example the build script contains:

```python
from config import FPVS_TOOLBOX_VERSION
cmd = ["pyinstaller", "-n", f"FPVS_Toolbox_{FPVS_TOOLBOX_VERSION}", ...]
```

Updating `FPVS_TOOLBOX_VERSION` is all that's required when releasing a new
version.


The build scripts locate the repository root automatically before running
PyInstaller, so they work even if launched from another directory.

## Packaging

Releases now provide an Inno Setup installer. Running the installer creates a
folder containing `FPVS_Toolbox.exe`, its required DLLs, and configuration
files. Manual installations can download this installer directly from the
GitHub release page and execute it to install the toolbox.

## Configuration

The look and feel of the interface can be tweaked by editing constants in
`config.py`.  In particular, several width settings control the advanced
processing window:

- `BUTTON_WIDTH`
- `ADV_ENTRY_WIDTH`
- `ADV_LABEL_ID_ENTRY_WIDTH`
- `ADV_ID_ENTRY_WIDTH`

Adjust these as desired to better fit your screen or preferences.

## Updating

When the toolbox starts it checks the GitHub releases API to see if a newer
version is available. If one is found you will be prompted to download and
install it. The updater downloads the installer for the new version and runs it
silently, replacing the existing installation.


The update check is controlled by constants in `config.py`:

- `FPVS_TOOLBOX_VERSION` – the current running version
- `FPVS_TOOLBOX_UPDATE_API` – URL queried for the latest release
- `FPVS_TOOLBOX_REPO_PAGE` – page opened when downloading updates

## Debug Logging

The toolbox routes messages through Python's ``logging`` module. At startup the
MNE-Python logger is set to ``WARNING`` to reduce output. Enable **Debug** mode
in the settings window and restart the application to raise the global log level
to ``DEBUG``. When debug mode is active the MNE logger is also increased to
``INFO`` so detailed processing information is visible.

