# FPVS Toolbox Product Scope

FPVS Toolbox is a PySide6 desktop application for FPVS EEG workflows. The
current release artifact is a Windows installer, while development and source
execution may take place on Windows 11 or CachyOS (Arch Linux). Shared runtime
decisions should remain portable across both without parallel implementations.

Primary user workflows:

- Create or open a project.
- Load BioSemi `.bdf` input data from the project input folder.
- Configure preprocessing settings.
- Run batch or single-file processing without blocking the GUI.
- Generate existing FFT/SNR and Excel outputs without changing output formats.
- Analyze outputs with the included statistics and visualization tools.

Current non-goals:

- Source Localization/eLORETA is removed from active runtime.
- EEGLAB `.set` loading is not supported.
- The historical `Legacy_App` and `PySide6_App` package names are not the target
  architecture.
