# Version 3 release notes

These notes describe the v3 changes relative to v2.1.2. Available installers and
their checksums are listed on the public
[FPVS Toolbox releases page](https://github.com/zcm58/FPVS-Toolbox/releases).
The first upgrade from v2.1.2 uses the full installer; follow the
[migration guide](migration-v3.md) before opening an existing project.

## Projects and processing

- Projects can register multiple groups and repeated sessions. Participant,
  group and recording identities come from the project manifest; grouped
  outputs remain separated. Missing visits are recorded without imputation.
- New projects can be created manually or imported from an FPVS Studio
  `.fpvsconfig` file. Review the imported protocol and recording folders before
  processing.
- Protocol settings record presentation rate, oddball rule, analyzed duration
  and trigger mappings. Recording-specific trigger schemas support explicitly
  reviewed acquisition differences.
- Optional preprocessing and post-processing QC screens have separate switches.
  New projects start with optional screens off; existing projects retain their
  saved choices. Trigger, geometry, finite-input, FFT-grid and output-completeness
  checks remain required.
- Shared dataset exclusions distinguish skipping processing from excluding
  processed data from analysis. Recording and condition decisions remain
  explicit, including for repeated visits.
- Processing records settings and input freshness. Changed preprocessing choices
  require processing again; stale downstream results require the indicated
  rebuild before analysis.

See [project setup and compatibility](index.md), the
[quick start](processing-quick-start.md), and
[QC review guide](reference/preprocessing-qc-review.md).

## Harmonics and output files

New projects default to **Dzhelyova/Poncet — stop after two consecutive failures**.
Existing projects without a versioned profile retain **Legacy FPVS Toolbox**.
Fixed/preregistered and significant-only exploratory profiles are also available.
Changing a profile changes the outcome definition; review it deliberately and
rebuild dependent results. Free Harmonic Clustering uses its own FullFFT-based
domain and does not inherit the standard Summed-BCA selected list.

New participant-condition exports pair a compact Excel workbook with lossless
NumPy spectral and metric companions. Existing Excel-only outputs remain
readable; they are not converted on opening. **Keep each workbook and its
companions together.** Long- and wide-format statistical workbooks remain
available for study-specific analyses outside the Toolbox. See
[spectral data files](reference/spectral-data-files.md) for the format and
[harmonic profiles](tools/statistics.md#summed-bca-and-harmonic-selection) for
selection rules.

## Default tools and beta tools

The default Workspace Tools are **Free Harmonic Clustering Analysis** and
**SNR Plots**. FHC supports defined paired-condition and independent-group
cluster-permutation contrasts; its guide describes the supported design and
correction families. SNR Plots provides condition and group spectra and
matching PNG/PDF figure exports.

The six opt-in beta tools are **Scalp Maps**, **Standard FPVS Screening**
(**Data Screening** in the sidebar), **Sensitivity Analysis**, **LORETA
Visualizer**, **Sequence Figure**, and **Individual Detectability**. Enable
them in **Settings > Experimental > Beta Tools**, save, and restart. Each
tool displays a beta notice on its first opening in an app session.

Use exported data with a prespecified external model when your scientific
question requires covariates, random slopes, longitudinal or nested models,
more than two groups, equivalence testing, or another unsupported estimand.
The built-in beta screening workflow does not replace study-specific modeling.
See the [tool overview](tools/index.md) for individual scope and limitations.

LORETA now includes linked MRI slice navigation, explicit current-map/shared/
fixed color limits, background previews, and cancellable source-map rebuilding.
The small-sample exact sign-flip p-value calculation and negative-tail cluster
handling have been corrected. Existing source maps retain their saved results
until **Rebuild source maps** is run. A retained cluster supports a cluster-level
finding, not a separate significance claim for each displayed location or a
between-condition contrast. See the [LORETA guide](tools/loreta-visualizer.md).

## Installation and compatibility

The application source and releases share the public **FPVS-Toolbox**
repository. V3 update checks use that address; published v2.1.2 binaries still
check the previous repository and require a manual download for their first v3
upgrade. V3 adds the separate
**FPVS Toolbox Update & Repair** application. The first upgrade from v2.1.2
uses the full installer; later releases may offer compatible patches.
Historical assets in **FPVS-Toolbox-Releases** remain available.

The supported processing workflow remains BioSemi ActiveTwo 64-channel BDF
with the documented BioSemi64 mapping. This release does not establish a
supported general-purpose EEG importer or a validated Unicorn analysis path.
Old outputs using different sensor geometry need the reprocessing review
described in the [migration guide](migration-v3.md#review-scientific-settings).

The Ratio Calculator, Image Resizer and legacy epoch-averaging tool are no
longer active tools. Existing raw recordings and saved analysis outputs remain
separate from the application installation.
