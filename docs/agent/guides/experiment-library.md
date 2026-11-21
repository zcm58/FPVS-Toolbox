# Experiment Library

Open **View → Experiment Library** from Welcome or an open project.
Public datasets can be downloaded with Toolbox unlinked from OpenFPVS, with an
account linked, or with a lab connection.

## Simulated FPVS-Oddball Demo

Simulated FPVS-oddball experiment. Download this to test FPVS Toolbox on your PC.

The demo has 32 synthetic participants, paired Red and Green oddballs, and
256 Hz BioSemi64 recordings. Select **Download and open** to install it under
your configured projects folder. The 251.1 MB archive contains approximately
436.3 MB of files, before processing outputs and optional source-localization
dependencies.

Toolbox displays download progress, verifies the archive and file checksums,
then prepares the project and opens Home. Select **Start Processing** to run the
normal pipeline. Cancel removes incomplete files. If an operation fails, read the
inline message and select **Try again**. An installed demo offers **Open project**,
including when the public catalog is unavailable. Reopening preserves your
local settings and processing outputs.

The project includes its 6 Hz base rate, 1.2 Hz oddball rate, condition markers
and three repetitions per condition. Each 40-second run contains 48 oddballs.
Toolbox's normal first-to-last-marker crop retains 45 complete cycles, giving
a 37.5-second analysis window. Reference plots and expected results accompany
the download. The simulated Red response is stronger than Green across the
cohort, providing a known result for exploring SNR Plots, Scalp Maps and statistics.

For experimental source visualization, enable Beta Tools in Settings and follow
the [LORETA Visualizer architecture](../../../src/Tools/LORETA_Visualizer/ARCHITECTURE.md). Its anatomy download
and source preparation are additional operations.

## Attribution

The dataset is released under CC BY 4.0 and includes `LICENSE`, `CITATION.cff`
and a recommended citation in its README. Credit the dataset when using it in
papers, presentations or shared derivatives. The reference citation is
Zackary Cole Murphy (2026), *Simulated FPVS-Oddball Demo*, version 1.0.0, OpenFPVS.
[Dataset provenance](https://openfpvs.com/public-library/v1/datasets/simulated-fpvs-oddball-demo/versions/1.0.0/provenance)
and [license terms](https://creativecommons.org/licenses/by/4.0/).
