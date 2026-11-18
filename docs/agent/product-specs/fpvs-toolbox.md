# FPVS Toolbox Product Scope

FPVS Toolbox helps researchers turn recorded FPVS EEG into reproducible,
project-owned results. The processing pipeline is the core product. Processing
methods and parameters are saved per project, and analysis and visualization
consume the processed results as optional next steps.

FPVS Studio and FPVS Toolbox ship as separate desktop applications, each with
its own package, installer and release version. Toolbox uses PySide6, ships a
Windows installer and also runs from source on CachyOS (Arch Linux).

OpenFPVS provides shared services and [desktop design guidance](../design-docs/DESIGN.md).
The apps exchange supported experiment configurations through a versioned
handoff. A shared launcher is an option for future consideration only.

## Workflow priority

1. Create a Toolbox project from a supported Studio setup or completed-session
   configuration, or enter the protocol manually for a study run elsewhere.
   Select the corresponding EEG recordings and review the hardware, protocol
   and recorded markers before processing.
2. Run the project's single-file or batch processing. The desktop stays
   responsive, and the project retains its settings and outputs for review
   and reruns.
3. Open SNR Plots and Scalp Maps through the Tools menu to inspect the processed
   response. For eligible projects, use the same menu to explore experimental
   source-space estimates in LORETA Visualizer.

Home centers on choosing recordings and running processing. Settings uses the
same compact window as Home, with the category list and save actions in view.

Welcome prioritizes **Open Existing Project…** for returning operators. Studio
import and manual setup are both available under **Create New Project…**.

## Current source and evidence

- **Studio configuration import.** **Import FPVS Studio Config…** creates a
  local project from the supported protocol and markers and retains their
  provenance. A cohort with one compatible protocol, hardware setup and
  recording per participant can already use one setup config, one EEG folder
  and Batch. A completed-session config adds evidence for one visit. Neither
  current format supplies the full study roster. [Accepted formats, scientific subset and recording review](../architecture/project-io.md#studio-config-handoff)
- **OpenFPVS Library.** Published data-only projects can be downloaded without
  an account and reopened locally. Selecting a shared study or publishing a
  reviewed analysis snapshot from Toolbox are future desktop workflows.
  [Current Library workflow](../guides/experiment-library.md) · [Platform ownership](../design-docs/DESIGN.md)
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

### Desktop workflow compatibility

When work moves behind the desktop UI, a user must still be able to reach the
operation from the same menu, shortcut or page, with the same defaults, draft
and confirmation prompts, and project or beta access rules. An active operation
keeps its existing navigation locks, progress, cancellation and retry behavior.
Results belong to the project and inputs that started the operation.

The [desktop workflow guide](../architecture/gui-backend.md#toolbox-workflow-owners)
owns the regression cases for repeated sessions, Sequence Figure, Individual
Detectability and reprocessing preflight.

## Future product goals

### Whole-study handoff after collection

After the last participant, the researcher marks collection complete in
Studio and exports one file for the study. Studio will organize the completed
project locally and update collection status for a linked OpenFPVS study.
Toolbox analysis has its own completion state. Local import and processing
remain available independently of an OpenFPVS connection.

The analyst imports the file once to create one Toolbox project, then selects
the raw EEG folder once. The recordings stay outside the handoff. Toolbox uses
the participant and visit roster, protocol revisions and retained evidence
from each execution to propose recording matches. One review shows incomplete
research attempts, visits without retained evidence, missing, extra or
ambiguous recordings, and incompatible protocol or hardware changes.
The analyst resolves the exceptions, then uses the existing Batch workflow
for the cohort. Repeated visits retain distinct recording identities.

Verify with a synthetic cohort containing a repeat visit, a missing EEG file
and a protocol revision. The review must identify the affected visits before
processing. Retain support for existing setup, completed-session and historical
configs across independently released apps. [Implementation and compatibility scope](../architecture/hardware-pipeline-studio-roadmap.md#target-complete-fpvs-studio-compatibility)

### Other goals

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
