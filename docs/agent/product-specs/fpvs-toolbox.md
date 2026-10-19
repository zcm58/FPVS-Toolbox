# FPVS Toolbox Product Scope

FPVS Toolbox's primary product is its FPVS EEG processing pipeline. Its target
is a modular processing package with methods and parameters selected and saved
per project. Analysis and visualization tools are secondary add-ons that consume
processing outputs; they must not become prerequisites for processing.

The current interface uses PySide6 and the release artifact is a Windows
installer, while development and source
execution may take place on Windows 11 or CachyOS (Arch Linux). Shared runtime
decisions should remain portable across both without parallel implementations.

Primary user workflows:

- Create or open a project.
- Register supported BioSemi64 `.bdf` or confirmed Brain Products `.vhdr`/`.bvrh`
  recordings with the project. Companion files are not separate participants.
- Seed a project from the supported subset of FPVS Studio `.fpvsconfig`
  schemas, then select and validate its recordings through Toolbox project APIs.
- Configure persisted project hardware, reference, montage, and supported
  preprocessing settings; changing confirmed hardware requires an explicit
  warning and invalidates incompatible processing state.
- Admit supported recordings through the project-local BIDS import boundary
  into MNE Raw and one shared numerical pipeline. BDF/BVCDF signal bytes are
  preserved; BVRF uses a labeled lossless FIF64 derivative, not standard raw
  EEG-BIDS.
- Run batch or single-file processing without blocking the GUI.
- Generate native `.fpvs` result anchors and numerical companions while retaining
  historical workbook readers and existing Excel report formats.
- Optionally analyze outputs with the included statistics and visualization
  tools.

Future product goals:

- Modular acquisition hardware and montage support through explicit profiles.
- A per-project pipeline editor for selecting, configuring, replacing, or
  omitting supported steps within resolved hardware/montage capabilities.
  This editor is not implemented. New method/order alternatives require
  versioned scientific contracts, cache invalidation, and explicit validation.
- Complete FPVS Studio compatibility across supported experiment-to-analysis
  workflows, with a verified version/schema matrix and end-to-end fixtures.

The [hardware, pipeline, and Studio roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
defines current foundations, gaps, ownership, and acceptance requirements.
Current source supports BioSemi64 and the bounded, confirmed Brain Products
routes documented in the [hardware guide](../../user/reference/brain-products.md).
The Unicorn reader remains gated and Studio import remains partial. Published
installer capabilities belong to their release tag, not this source branch.
Preserve trusted numerical results, locked processing order, and existing
project compatibility during extension work.

Current boundaries:

- The historical `Tools.SourceLocalization` implementation is retired. The
  separate LORETA Visualizer is an opt-in beta tool with isolated source
  producers and a renderer that consumes prepared payloads.
- EEGLAB `.set` loading is not supported.
- The historical `Legacy_App` and `PySide6_App` package names are not the target
  architecture.
