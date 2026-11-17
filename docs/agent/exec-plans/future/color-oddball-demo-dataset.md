# Simulated FPVS-Oddball Demo for FPVS Toolbox

**Status** · Dataset reference specification. Native implementation and public
delivery are tracked in the [active plan](../active/public-experiment-library.md).

A user can download a simulated companion to the Studio Color Oddball Demo,
process it with Toolbox, and see how a known within-participant effect appears
in SNR spectra, scalp maps, statistics, and experimental source estimates.

## Dataset and timing

| Decision | Proposed v1 |
| --- | --- |
| Cohort | 32 synthetic participants in one group, with one continuous BDF per participant. Every participant completes both conditions. |
| Signals | 256 Hz, classic 24-bit BDF. Canonical BioSemi64 scalp labels, synthetic EXG1 and EXG2 reference signals, and a final digital Status channel. |
| Protocol | Color Oddball Demo 1.0.0. Red and Green oddballs, three blocks with one run per condition, 40 seconds per run, 6 Hz base and 1.2 Hz oddball. Balance within-block condition order across participants. |
| Events | Red onset 1, Green onset 2, shared oddball marker 55, and 48 oddball presentations in each run. The first oddball occurs 2/3 s after each run starts. Round each absolute presentation time to the nearest sample and emit a short zero-separated Status pulse. Keep a sample-indexed event ledger. |
| Analysis window | Toolbox's normal first-to-last oddball crop rounds 47 marker intervals down to 45 on-bin cycles. Each 40-second run yields 37.5 analyzed seconds, 9,600 samples, and 0.026667 Hz bin spacing. The 1.2 Hz and 6 Hz peaks are exactly at bins 45 and 225. |
| Size | At 264 recorded seconds per file, with 2 seconds at each end and 4 seconds between runs, the 32 BDFs total about 435 MB (415 MiB) before ZIP compression. Pilot the real compression ratio, show the measured transfer size in the Library, and record the local disk requirement separately. |

Classic BDF puts digital trigger information in the final Status channel. The
current Toolbox BioSemi path validates the canonical montage and reference layout.
[BioSemi BDF format](https://www.biosemi.com/faq/file_format.htm) ·
[MNE BDF reader](https://mne.tools/stable/generated/mne.io.read_raw_bdf.html) ·
[Toolbox loading contract](../../architecture/eeg-loading-contract.md)

The acquisition schedule and crop are both part of the tutorial. Use the real
48-marker sequence and state the 45-cycle crop on the dataset detail page and
in the README. A 40-second FFT would require an extra closing marker outside
the Studio sequence. The fixation task is part of the companion Studio
protocol. The Toolbox dataset models the tagged EEG and carries no behavioral
scores. [Toolbox crop contract](../../architecture/fft-crop-method.md)

## Simulated effect and expected outputs

- Give both conditions the same distribution of base responses at 6 Hz and its
  harmonics. Add a phase-locked posterior oddball response in both conditions,
  with declining energy at 1.2, 2.4, 3.6 and 4.8 Hz. Give Red greater mean
  amplitude, with participant-to-participant overlap and some Green-stronger
  pairs. Build in a smaller Red–Green difference centrally than posteriorly.
- Forward-project a medial occipital base source and bilateral occipitotemporal
  oddball sources through the canonical montage. Add spatially correlated
  colored noise, posterior alpha and modest run-level variation independent of
  condition. Keep generator seeds, source locations, input gains and the fixed
  quantization policy in the release provenance. The template geometry makes
  this a controlled demonstration. [MNE EEG forward model](https://mne.tools/stable/auto_tutorials/forward/35_eeg_no_mri.html) ·
  [FPVS source analysis example](https://pmc.ncbi.nlm.nih.gov/articles/PMC8463833/)
- Freeze a release acceptance check on 32 participant-level differences.
  Compute Red minus Green in the right occipitotemporal ROI (P8, P10, PO8,
  PO4, O2) using baseline-corrected amplitudes summed across the four
  prespecified oddball harmonics. Align each repetition at the first oddball,
  average the signed waveforms within participant and condition, and apply
  Toolbox's canonical FFT and local-noise subtraction. Require a positive
  estimate and two-sided paired p < .05, and
  record the observed difference in µV, 95% CI and Cohen's dz. Aim for a
  moderate effect with overlapping distributions. Freeze the procedure and
  release seed before evaluating the full release.
- Walk users through the native **Standard FPVS Screening** workflow with ROT,
  LOT and Central using the stock ROI definitions and saved Toolbox harmonic
  selection. Check that the Condition × ROI interaction and positive Red–Green
  ROT contrast survive the tool's Holm corrections. That fitted-model contrast
  and the independent paired acceptance check use their stated analysis rules.
  The synthetic separation teaches the workflow and makes no claim about human
  responses to red and green. [Toolbox statistics contract](../../architecture/statistics-tools.md)

## Toolbox and OpenFPVS experience

1. **View → Experiment Library** opens the public dataset browser, matching
   the menu path Studio users already know. Make it available on the Welcome
   screen and from an open project. Use the Studio Library's hierarchy and
   stage feedback with native Toolbox components. Show **Simulated FPVS-Oddball Demo**
   with a **Simulated EEG** label, 32 participants, two conditions, 256 Hz and
   the actual download size. **Download and open** uses the configured Toolbox
   project root. An installed copy offers **Open project**.
2. Stream and verify the versioned package in a worker. Show **Downloading
   dataset**, **Verifying files**, and **Setting up project** as the work changes.
   Keep the status row readable with reduced motion. A cancel or failed
   verification leaves no partial project, and reopening an installed copy
   preserves its processed results. Reuse normal save and project-handoff guards.
3. Open the standard Toolbox workspace with all 32 participants and the timing
   and event map already set. The user selects **Start Processing** from Home.
   After processing, the tutorial uses **SNR Plots** to compare spectra,
   **Scalp Maps** to compare posterior oddball amplitude on a common scale,
   and **Standard FPVS Screening** to inspect the paired condition pattern.
   Show a common 6 Hz peak in the spectra for context.
4. Enable **Settings → Experimental → Beta Tools** and reopen Toolbox for
   **LORETA Visualizer**. Generate its source-ready
   derivatives and save the current harmonic selection using the ordinary
   processing path. Guide users to build a Red/Green cortical comparison
   first and optionally the eLORETA volume view. Show Red minus Green as
   descriptive. Use the existing fsaverage download and cache when needed,
   with its size and preparation reported separately from EEG processing.
   [LORETA workflow](../../../user/tools/loreta-visualizer.md)
5. Add the companion to the same Color Oddball Demo page on OpenFPVS as
   **Simulated EEG for Toolbox**. Publish through an explicitly approved
   anonymous dataset record linked to the immutable Studio item and version.
   Always use the public catalog and download routes without credentials.
   The dataset stays available with Toolbox unlinked, with an OpenFPVS account
   linked, and with or without lab membership. Keep the opened demo local,
   with the Studio release link stored as provenance.
   Add a typed public dataset catalog and download contract with version,
   compatibility, signed size and digest, and withdrawal. Verify the
   existing Studio experiment catalog and downloads still work. One versioned, data-only ZIP contains a portable
   Toolbox project manifest, 32 BDF inputs, protocol and generation
   provenance, a README, and the measured reference results. Pin the project
   protocol to 45 analyzed cycles at 256 Hz. Use relative paths and the
   normal Toolbox opener. The portable manifest avoids
   depending on the current version mismatch between Studio config exports
   and Toolbox's config helper. [Toolbox project I/O](../../architecture/project-io.md)

## Implementation and acceptance

1. Make a four-participant end-to-end fixture first. Validate the BDF header,
   reference channels, decoded markers, three repetitions per condition, and exact
   on-bin span through Toolbox's actual import and preprocessing. Produce
   valid SNR and scalp outputs and open one source comparison from ordinary
   derivatives before scaling the cohort.
2. Freeze and build the complete cohort. Clean-profile processing must retain
   all 32 pairs, recover the expected base and oddball structure, and meet
   the paired and native Stats criteria. Compare the source display with
   the injected posterior ground truth at regional scale. Record time for
   first processing and a cached repeat, with machine, app version and cache
   state. Record download and optional anatomy/source-build times separately.
3. Implement the Library and public companion. Exercise **View → Experiment
   Library** on Welcome and with a project open. Verify public discovery and
   download in an unlinked install, with a linked account outside any lab, and
   with a lab-linked account. Check version and digest validation, archive
   traversal and size rejection, cancellation, retry, offline reopening, and
   the walkthrough in a fresh installed Toolbox. Test Light/Dark, keyboard use, reduced
   motion, and the workspace at 1280 × 900. Publish only
   after final byte size, compatibility, license and reference results are
   measured and recorded.

## Feasibility evidence

On 2026-11-16, Toolbox's marker-integrity planner accepted all six occurrences
from an in-memory schedule with the proposed codes and exactly 48 markers per
run. Each proposed span was 9,600 samples, with 213- or 214-sample marker
spacing. The four-participant pilot and the 32-participant BDF cohort then
completed native Toolbox processing. The full run released 64 paired
participant-condition results, matched pooled oddball SNR targets of 1.50,
2.40, 3.10 and 1.80, and kept each condition's base SNR above 15 at 6–48 Hz.
The prespecified paired ROT contrast was +0.86 µV, with a two-sided
paired p = 0.000004. Clean-install delivery and a source-map round trip
remain acceptance work.
