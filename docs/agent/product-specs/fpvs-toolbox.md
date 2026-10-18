# FPVS Toolbox Product Scope

FPVS Toolbox is a PySide6 desktop application for FPVS EEG workflows. The
current release artifact is a Windows installer, while development and source
execution may take place on Windows 11 or CachyOS (Arch Linux). Shared runtime
decisions should remain portable across both without parallel implementations.

Primary user workflows:

- Create or open a project.
- Load supported BioSemi64 `.bdf` input data from the project input folder.
- Seed a project from the supported subset of FPVS Studio `.fpvsconfig`
  schemas, then select and validate its recordings through Toolbox project APIs.
- Configure preprocessing settings.
- Run batch or single-file processing without blocking the GUI.
- Generate native `.fpvs` result anchors and numerical companions while retaining
  historical workbook readers and existing Excel report formats.
- Analyze outputs with the included statistics and visualization tools.

Future product goals:

- Modular acquisition hardware and montage support through explicit profiles.
- A shared processing pipeline that can select, replace, or omit steps according
  to the resolved montage/hardware policy and reviewed scientific method.
- Complete FPVS Studio compatibility across supported experiment-to-analysis
  workflows, with a verified version/schema matrix and end-to-end fixtures.

The [hardware, pipeline, and Studio roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
defines current foundations, gaps, ownership, and acceptance requirements.
Production processing is still BioSemi64; the Unicorn reader is gated and Studio
import is partial. Preserve trusted BioSemi results and existing project
compatibility during this extension work.

Current boundaries:

- The historical `Tools.SourceLocalization` implementation is retired. The
  separate LORETA Visualizer is an opt-in beta tool with isolated source
  producers and a renderer that consumes prepared payloads.
- EEGLAB `.set` loading is not supported.
- The historical `Legacy_App` and `PySide6_App` package names are not the target
  architecture.
