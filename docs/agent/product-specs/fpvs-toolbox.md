# FPVS Toolbox Product Scope

FPVS Toolbox prepares recorded FPVS EEG for analysis. The processing pipeline
produces project-owned, quality-controlled data and exports with the methods,
parameters and exclusions needed to interpret them. The lab conducts its
official statistical analysis in its chosen external software. Toolbox's
existing screening, statistics, plots and maps support exploratory work and QC.

FPVS Studio and FPVS Toolbox ship as separate desktop applications, each with
its own package, installer and release version. Toolbox uses PySide6, ships a
Windows installer and also runs from source on CachyOS (Arch Linux).

OpenFPVS provides shared services and [desktop design guidance](../design-docs/DESIGN.md).
The apps exchange supported experiment configurations through a versioned
handoff. A shared launcher is an option for future consideration only.

Plan for FPVS studies of up to approximately 100 participants. Use about 200
recordings as the practical sizing target for two-session performance and
capacity checks, assuming one recording per participant per session.

## Workflow priority

1. Create a Toolbox project from a supported Studio setup or completed-session
   configuration, or enter the protocol manually for a study run elsewhere.
   Select the corresponding EEG recordings and review the hardware, protocol
   and recorded markers before processing.
2. Run the project's single-file or batch processing. The desktop stays
   responsive, and the project retains its settings and outputs for review
   and reruns.
3. Open the analysis-ready Excel results for external analysis. SNR Plots and
   Scalp Maps offer optional checks of the processed response. Eligible projects
   can also explore experimental source-space estimates in LORETA Visualizer.

Home centers on choosing recordings and running processing. Settings uses the
same compact window as Home, with the category list and save actions in view.

Welcome prioritizes **Open Existing Project…** for returning operators. Studio
import and manual setup are both available under **Create New Project…**.

OpenFPVS lists study results separately for each contributing lab. Analysts
download the lab-specific data and combine them manually in their external
tools. Tutorials belong on the OpenFPVS website, with YouTube tutorials
planned. Keep instructions needed to complete a desktop action beside it.

**Share study results…** is available for a reviewed cohort with a verified
OpenFPVS destination. An analyst connects the lab computer and explicitly
shares the current full-audit release. The upload preserves canonical ROI
values, the processed scope, reviewed exclusions and visits awaiting EEG.
Offline retries use the same revision. [Reporting ownership and verification](../../../src/Main_App/reporting/AGENTS.md)

## Current source and evidence

- **Studio configuration import.** **Import FPVS Studio Config…** creates a
  local project from the supported protocol and markers and retains their
  provenance. A cohort with one compatible protocol, hardware setup and
  recording per participant can already use one setup config, one EEG folder
  and Batch. A completed-session config adds evidence for one visit. A
  whole-study export supplies the roster for an explicit review and can update
  the same analysis project. [Accepted formats, scientific subset and recording review](../architecture/project-io.md#studio-config-handoff)
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
  save and restart, and the first-open notice in each session. In **Tools →
  Beta Tools → Scalp Maps**, **View in 3D** opens the selected
  electrode maps on a rotatable head. Drag to rotate, scroll to zoom, and
  Shift-drag to pan. Switch maps to compare them from the same angle. Use
  **Export view…** in the viewer to save that angle as PNG and PDF, or choose
  **3D front and back** under **Export view** on the Generate Maps page for
  standardized views. **3D back + 2D top** publishes both projections together
  with one color scale and a label for each method. All 2D top views retain
  cubic interpolation. The 3D colors blend between neighboring electrodes
  using natural-neighbor interpolation. All projections use the same
  electrode measurements. Scalp Maps accepts the released montage's own names
  and positions. **Advanced Settings → Fallback montage** supplies positions
  for recordings that lack them using a matching cap template or coordinate file.
  Current LORETA
  generation requires eligible source-ready derivatives and current harmonics.
  Analysis workbooks finish independently. On first open, LORETA prepares any
  required source maps for eligible single-session projects and shows build
  progress. The estimates are exploratory. [Desktop tools](../architecture/gui.md) ·
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

<a id="future-product-goals"></a>

## Cross-app workflow and release direction

For the coordinated desktop changes, establish Studio's study lifecycle and
export first, then verify Toolbox against that producer. Record additional
feature candidates after the two apps agree on the workflow.

### Whole-study handoff after collection

After the last participant, the researcher marks collection complete in
Studio and exports one file for the study. Studio organizes the completed
project locally. Its separately authorized website connection owns linked
collection status.
Toolbox processing and release of analysis-ready outputs have their own
completion state. Local import and processing remain available independently
of an OpenFPVS connection.

The maintained Studio and Toolbox sources implement this offline workflow.
The analyst imports the file once to create one Toolbox project, then selects
the raw EEG folder once. The recordings stay outside the handoff. Toolbox uses
the participant and visit roster, protocol revisions and retained evidence
from each execution to propose recording matches. One review shows incomplete
research attempts, visits without retained evidence, missing, extra or
ambiguous recordings, and incompatible protocol or hardware changes.
When Studio's protocol changed during collection, identify the affected
conditions, the reason recorded for the change, and which visits used each
revision. Keep earlier visits tied to
their original stimuli and settings. Flag incompatible revisions before any
analysis combines those visits.
The analyst resolves the exceptions, then uses the existing Batch workflow
for the cohort. Repeated visits retain distinct recording identities.

A Studio experiment saved as a new standalone study has its own source-study
identity and opens in its own Toolbox analysis project, even if its protocol
is identical to the original. Restoring an earlier protocol inside the
original study preserves its identity and the revision recorded for each visit.

**Review the cohort.** Open on exceptions and show counts for the full roster.
For example, show 29 clear matches and one ambiguous visit, with the full
roster one click away. Ask the analyst to confirm the clear matches once as a
group. Resolve ambiguous matches individually. If one of 30 recordings is
missing, the analyst can explicitly defer it and process the 29 eligible
recordings. Retain the outstanding visit in the roster. Track deferral
separately from an exclusion made after QC.

**Choose an experiment version.** Default to one version for group analysis.
Combining compatible versions requires an explicit override and two warnings,
each requiring confirmation that the versions may be scientifically
noncomparable. Identify the revisions, conditions and visits involved.
Method-incompatible settings continue to block the affected analysis.

**When the study grows after processing.** Toolbox identifies the existing
analysis project for the same Studio study and previews the revision using
the saved EEG folder. Show added participants, additional visits
and changed evidence. Retain recording matches and review decisions whose
evidence still holds. The analyst reviews new or changed visits, then confirms
the update in place. Cancelling leaves the project as it was. Importing the
same revision again adds nothing and preserves completed reviews.
If a revised handoff omits a previously processed visit, show that discrepancy
and preserve the visit, its reviews and its results. Require an explicit
resolution before changing cohort membership.

Keep the original import roster and the full roster behind each completed
analysis. For example, adding participant 21 leaves the previous result
identified as the analysis of 20 participants. Tell the analyst it is outdated
for the expanded cohort. The notice is dismissible and the earlier results and
evidence remain available. Present Toolbox outputs as current for the expanded
cohort after processing and the affected analyses run again. The analyst
reruns official analyses externally. Reuse per-recording work
where its inputs, settings and outputs still pass the existing checks.

Confirming new raw recordings stages them for processing and invalidates dependent
outputs. Importing a revised Studio handoff compares both rosters before confirmation.
After a roster change Toolbox shows a notice and retains the prior cohort's result.
[Current registration and release rules](../architecture/project-io.md#multi-group-processing-foundation)

Verify with a synthetic cohort containing a repeat visit, a missing EEG file
and a protocol revision. The review must identify the affected visits before
processing. Add a new participant and a new visit for an existing participant
after analysis. Check the preview, cancel it, then confirm and import the same
revision again. Verify one project contains each visit once, unchanged reviews
survive, and the previous analysis still identifies its original cohort.
Retain support for existing setup, completed-session and historical
configs across independently released apps. [Implementation and compatibility scope](../architecture/hardware-pipeline-studio-roadmap.md#target-complete-fpvs-studio-compatibility)

### After Batch processing

The Last run panel counts completed, reused, excluded, failed and unfinished
files separately. After Batch, **Open Excel Results** opens the full-audit
workbook produced by the run after verifying its current selection fingerprint.
**SNR Plots** and **Scalp Maps** reuse the Tools commands, including the Scalp
Maps beta setting and scientific eligibility checks. Output-folder and
issue-review actions remain available. **Share study results** opens the review
for a linked Studio study with a full-audit workbook. The
[full-audit workbook](../architecture/post-processing-export-contract.md#full-audit-analysis-ready-workbook)
already supports external statistics when its release requirements are met.

### Other goals

- [Automatic error and crash reporting](../architecture/diagnostics.md#automatic-error-and-crash-reporting-planned)
  through the shared FPVS-Studio-Feedback service, with a Toolbox diagnostics preference.
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
