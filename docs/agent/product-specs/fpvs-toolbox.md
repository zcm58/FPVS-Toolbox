# FPVS Toolbox Product Scope

FPVS Toolbox helps researchers turn recorded FPVS EEG into reproducible,
project-owned results. The processing pipeline is the core product. Processing
methods and parameters are saved per project, and analysis and visualization
consume the processed results as optional next steps.

The desktop application uses PySide6 and ships as a Windows installer. Source
development and execution also support CachyOS (Arch Linux) through the shared
runtime.

## Workflow priority

1. Bring a completed experiment from FPVS Studio into Toolbox. Import a
   supported Studio configuration, select the corresponding EEG recordings, and
   review the hardware, protocol, and recorded markers before processing.
2. Run the project's single-file or batch processing. The desktop stays
   responsive, and the project retains its settings and outputs for review
   and reruns.
3. Open SNR Plots and Scalp Maps through the Tools menu to inspect the processed
   response. For eligible projects, use the same menu to explore experimental
   source-space estimates in LORETA Visualizer.

Home centers on choosing recordings and running processing. Settings uses the
same compact window as Home, with the category list and save actions in view.

Manual project creation and recording setup remain supported for studies run
outside Studio. Welcome prioritizes reopening an existing project for processing
or review. Studio import and manual setup are available under Create New Project.
Relative usage frequency has yet to be measured.

## Current source and evidence

- **Studio configuration import.** Import FPVS Studio Config is available from
  Welcome > Create New Project and from File. It imports the Toolbox-owned
  project, protocol and marker subset of `.fpvsconfig` schemas 1.0.0–1.8.0
  for FPVS Oddball and Cognitive Load FPVS, including optional removed-electrode
  metadata. Users choose the hardware and recordings in Toolbox. The separate
  acquisition-evidence adapter can compare ordered marker codes after reviewed
  recording association. End-to-end receiver integration and qualification
  remain open. [Studio roadmap](../architecture/hardware-pipeline-studio-roadmap.md)
- **Recording preparation.** Confirmed BioSemi ActiveTwo64, ActiveThree,
  Brain Products and Unicorn Hybrid Black have scoped software routes into the
  project-local BIDS adapter and shared MNE processing pipeline. The documented
  format and montage limits govern which recordings can be admitted. Changing
  the hardware profile requires confirmation and invalidates incompatible
  results. [Recording routes](../architecture/eeg-loading-contract.md#supported-project-routes)
- **Outputs and tools.** Processing generates native `.fpvs` result anchors
  and numerical companions. Historical workbook readers and Excel report
  formats remain supported. SNR Plots and Free Harmonic Clustering are enabled
  by default. Scalp Maps and LORETA Visualizer require the Beta Tools setting,
  save and restart, and the first-open notice in each session. Current LORETA
  generation requires eligible source-ready derivatives and current harmonics.
  Automatic generation is limited to single-session inputs, and the estimates
  are exploratory. [Desktop tools](../architecture/gui.md) ·
  [LORETA architecture](../../../src/Tools/LORETA_Visualizer/ARCHITECTURE.md)

Source tests and synthetic examples establish software behavior within their
tested inputs. Physical EEG recording and stimulus timing require separate
hardware measurements. The published installer has its own version and
acceptance evidence. [Release ledger](../exec-plans/active/v3-release-readiness.md)

## Workflow acceptance

Use a paired, sanitized Studio export and supported EEG fixture. A user can
import the config, review its populated protocol and recording selection,
resolve missing or incompatible inputs, and complete processing. Current
outputs open in SNR Plots and Scalp Maps, with beta access enabled for the
latter. An eligible single-session project can open an experimental LORETA
estimate, while unavailable derivatives keep that review blocked. Verify that
manual setup can still create and process a supported project and that existing
projects reopen with their saved inputs and results. Track Studio version and
schema coverage in the roadmap.

## Future product goals

- Modular acquisition hardware and montage support through explicit profiles.
- A per-project pipeline editor for selecting, configuring, replacing, or
  omitting supported steps within resolved hardware/montage capabilities.
  This editor is not implemented. New method/order alternatives require
  versioned scientific contracts, cache invalidation, and explicit validation.
- Complete FPVS Studio compatibility across supported experiment-to-analysis
  workflows, with a verified version/schema matrix and end-to-end fixtures.

Preserve trusted numerical results, locked processing order, and existing
project compatibility during extension work.

## Current boundaries

- The historical `Tools.SourceLocalization` implementation is retired. The
  separate LORETA Visualizer is an opt-in beta tool with isolated source
  producers and a renderer that consumes prepared payloads.
- EEGLAB `.set` loading is not supported.
- The historical `Legacy_App` and `PySide6_App` package names are not the target
  architecture.
