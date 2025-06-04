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
