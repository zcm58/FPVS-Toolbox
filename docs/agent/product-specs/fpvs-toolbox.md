# FPVS Toolbox Product Scope

FPVS Toolbox is a Windows-oriented PySide6 desktop application for FPVS EEG
workflows.

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
