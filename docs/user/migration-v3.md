# Upgrading from v2.1.2 to v3

V3 changes project metadata, harmonic-profile selection and newly written
spectral files, and adds a separate updater. Opening an old project does not
reprocess it or turn its old numerical outputs into v3 results.

## Upgrade with the full installer

1. Finish active processing and exports, then close every Toolbox window.
2. Keep a backup of each project folder, including `project.json`, QC decisions,
   outputs and any spectral companions, plus raw recordings stored elsewhere.
   Preserve the v2.1.2 environment and outputs if you must reproduce that analysis.
3. Use v2.1.2's update check after the stable v3 release is published, or download
   the full `FPVSToolbox-<version>-setup.exe` from the
   [public releases page](https://github.com/zcm58/FPVS-Toolbox-Repo/releases).
   For a direct download, check the matching SHA-256 before running the installer.
   Retain the existing installation scope.
4. Open Toolbox and check the version in **File > About…**. Open an existing
   project using **File > Open Existing Project…** and review its settings before
   starting work.

Both versions use the FPVS-Toolbox-Repo release address; the source repository's
return to public visibility removes the address-related manual-upgrade
requirement. The full installer establishes the new updater and application
inventory. A patch is not a migration path from v2.1.2. Later checks use **File > Check for
Updates**; repair is available through **FPVS Toolbox Update & Repair** in the
Windows Start menu. See [installation instructions](installing-and-updating.md).

Keep projects and raw data outside the application installation directory.
Application replacement is designed to preserve user data; a project backup
also preserves the exact pre-upgrade analysis state. Do not assume a project
saved by v3 can be opened by v2.1.2; use the preserved copy for that workflow.

## Review scientific settings

| Item | What to review before regenerating results |
| --- | --- |
| Protocol | Verify presentation rate, oddball rule, analyzed duration, condition-start codes and oddball markers against the acquisition records. Imported Studio settings still need this review. |
| Harmonic profile | Old projects without a versioned profile resolve to **Legacy FPVS Toolbox**. New projects use **Dzhelyova/Poncet — stop after two consecutive failures**. Moving an old study to a different profile is an explicit analysis change. |
| Sensor geometry | Current processing uses MNE BioSemi64 geometry. Reprocess old outputs using generic `standard_1005` coordinates before new analysis when interpolation or a geometry-based channel decision was involved. Regenerate old scalp maps even without interpolation. Do not pool mixed-geometry results. |
| Channel labels | Use anatomical labels, or select the A1-A32/B1-B32 mapping only for standard BioSemi 64-channel 10/20 wiring. Custom and ABC/equiradial layouts are not covered. |
| Optional QC | Existing projects preserve their saved choices and historical defaults; new projects start optional screens off. Review **Settings > Experimental** rather than assuming two projects use the same screens. |
| Groups and visits | Confirm canonical participant/group/recording assignments in the project. Do not move output files between group folders to change membership. |
| Exclusions | Review **Settings > Quality Control > Manage Dataset Exclusions…** and any condition-specific decisions. Turning off a QC screen does not erase saved exclusions or reverse completed repairs. |

The [methods reporting checklists](reference/methods-reporting-checklist.md)
describe what to record when a processing or analysis definition changes.

## Rebuild only the required stage

- Changed preprocessing, sensor geometry or preprocessing QC choices require
  **Start Processing**. The app checks each recording's saved processing choices;
  processing one recording does not refresh every recording.
- If a tool reports that saved FullFFT provenance predates the current BioSemi64
  and project-frequency-protocol contract, reprocess the EEG with **Start
  Processing**. An older workbook can remain readable while failing this
  analysis check; **Resume Post-processing** alone does not repair it.
- Changed post-processing QC or analysis exclusions require regenerated
  downstream outputs. Use **Resume Post-processing** when it is offered.
- Changed harmonic definitions require **Settings > Harmonics > Recalculate
  Harmonics** or the rebuild offered when saving the changed settings. This does
  not repair an incomplete raw-processing result.
- For LORETA maps created before the corrected exact permutation calculation,
  use **Source Map Options > Rebuild source maps**. Source-ready inputs must be
  current. Previously saved maps are not silently rewritten on opening.

Follow an explicit stale-output or incomplete-output message before running
downstream tools. **File > Reset Project Processing Cache...** removes managed
caches and the incremental completion index; it preserves raw BDFs, settings,
manual QC choices and current outputs. The next processing run recomputes from
raw data and replaces the outputs it regenerates. Cache reset is not an undo
operation or a replacement for reviewing changed settings.

## Keep new output companions with their workbooks

Existing Excel-only outputs remain readable. New processing writes a compact
condition workbook with `.spectra.<hash>.npz` and `.metrics.<hash>.npz`
companions. Copy or back up all three together, without renaming them. The
long/wide statistical Excel exports remain available for external analysis.

If a companion is missing, restore it from backup or reprocess the affected
recording. A downstream refresh cannot reconstruct missing spectral arrays.
See [spectral data files](reference/spectral-data-files.md) for script-reader
examples and format details.

## Find the tools

**Free Harmonic Clustering** and **SNR Plots** are the default tools. Six other
tools are hidden until Beta Tools is enabled and the app is restarted; their
scope is listed in the [tool overview](tools/index.md). General study-specific
statistical modeling belongs in your planned external analysis using the
exported data. The Ratio Calculator, Image Resizer and legacy epoch-averaging
tool are not part of the v3 tool inventory.
