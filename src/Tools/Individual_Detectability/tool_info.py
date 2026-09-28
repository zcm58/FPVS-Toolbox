"""Editable user-facing information for the Individual Detectability tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
Individual Detectability creates participant-level summed-harmonic z-score
topographies and SNR panels for processed FPVS conditions. Each panel reports
the number of electrodes meeting the selected z-score and optional
Benjamini-Hochberg FDR criteria. The default workflow uses the project-wide
selected harmonics saved when processing completed.
</p>

<h3>How the Composite Z-Score Is Calculated</h3>
<ol>
  <li>Read the participant's uncorrected <b>FullFFT Amplitude (uV)</b>
  spectrum for the condition. Normal project processing averages retained
  repetitions in time before computing the FFT.</li>
  <li>Sum the amplitudes at the selected oddball harmonics.</li>
  <li>For each matching relative offset, sum the neighboring amplitudes
  across those same harmonics. The offsets are -10 through -2 and +2
  through +10 FFT bins; the target and immediately adjacent bins are excluded.
  This retains 18 background sums, rather than pooling all neighboring bins
  or collapsing them to one noise value.</li>
  <li>Remove one minimum and one maximum from the summed background,
  normally leaving 16 values. Calculate their mean and population standard
  deviation (ddof = 0).</li>
  <li>Calculate <b>Z = (summed target amplitude - mean summed background)
  / SD of summed background</b>, separately for each electrode.</li>
</ol>
<p>
This is a within-participant spectral comparison, not standardization of
stored summed-BCA values across participants. Trimming the background after
summation can also differ from summing separately baseline-corrected harmonics.
</p>

<h3>Detection and Display</h3>
<p>
The default electrode rule is <b>Z &gt;= 1.64</b> together with one-tailed
Benjamini-Hochberg FDR at alpha = 0.05 across electrodes. Advanced settings
allow the threshold and correction to be changed. The displayed <b>n</b> is
the number of significant electrodes. The current tool reports electrode
results; it does not provide ROI-level detection results.
</p>
<p>
The SNR panel averages stored FullSNR curves across significant electrodes
and selected harmonics. It is a separate descriptive display, not the summed
raw background used to calculate Z. Its half-window setting affects only
that display. The panel is blank when no electrode meets the detection rule.
</p>

<h3>Harmonic Selection</h3>
<p>
Choose the processed Excel root, select conditions and participants, confirm
output options, then run the analysis. Advanced settings control exploratory
custom harmonics, thresholds, and correction options. Custom
harmonics do not replace the saved project selection.
</p>

<h3>Published Methods and Toolbox Choices</h3>
<p>
The references below support summed-spectrum individual detection, but their
harmonic domains, noise windows, and decision rules differ. These citations
do not mean that the toolbox reproduces every study's settings.
</p>
<ul>
  <li><b>David et al. (2025)</b>, Sections 2.6 and 3.2 and Figure 5:
  sums 25-bin harmonic-centered segments before baseline correction and
  reports FDR-corrected individual topographies, significant-electrode counts,
  and SNR panels. Its summed-amplitude background retains 20 values after
  adjacent-bin and min/max exclusions. The paper does not specify the
  toolbox's exact Benjamini-Hochberg variant or alpha.</li>
  <li><b>Yan et al. (2023)</b>: uses five oddball components, 48 neighboring
  bins, and an individual ROI criterion of Z &gt; 1.64.</li>
  <li><b>Hauk et al. (2025)</b>, Section 2.5.2: explicitly sums
  harmonic-centered spectra before baseline correction and Z-scoring, with
  ten neighboring bins per side, a one-bin gap, and min/max removal.
  The toolbox uses nine neighbors per side before trimming.</li>
  <li><b>Lochy et al. (2024)</b>, Section 3.4: describes individual ROI
  Z-scores from uncorrected summed harmonic amplitudes with Z &gt; 1.64.
  That description is less explicit about intermediate bin summation.</li>
</ul>

<h3>References</h3>
<ol>
  <li>David, J., et al. (2025).
  <a href="https://doi.org/10.1016/j.clinph.2024.12.018">An objective and
  sensitive electrophysiological marker of word semantic categorization
  impairment in Alzheimer's disease</a>.
  <i>Clinical Neurophysiology, 170</i>, 98-109.</li>
  <li>Yan, X., Volfart, A., &amp; Rossion, B. (2023).
  <a href="https://doi.org/10.1038/s41598-023-40852-9">A neural marker of
  the human face identity familiarity effect</a>.
  <i>Scientific Reports, 13</i>, 16294.</li>
  <li>Hauk, O., et al. (2025).
  <a href="https://doi.org/10.1162/imag_a_00414">Word-selective EEG/MEG
  responses in the English language obtained with fast periodic visual
  stimulation (FPVS)</a>. <i>Imaging Neuroscience, 3</i>.
  <a href="https://github.com/olafhauk/FPVS_WORDS">Authors' analysis code</a>.</li>
  <li>Lochy, A., et al. (2024).
  <a href="https://doi.org/10.1016/j.cortex.2024.01.007">Linguistic and
  attentional factors - Not statistical regularities - Contribute to
  word-selective neural responses with FPVS-oddball paradigms</a>.
  <i>Cortex, 173</i>, 339-354.</li>
</ol>

<h3>Repeated Sessions</h3>
<p>
This tool is currently disabled for repeated-session projects because its
participant-keyed collection is not yet recording-aware. The protective gate
prevents one visit from overwriting another. Use a session-aware SNR, Scalp
Maps, Stats, or long-export workflow instead.
</p>

<h3>Interpretation Notes</h3>
<p>
Individual-level detectability is a review and reporting aid. Check the chosen
harmonics, FDR settings, and excluded participants before comparing results
across conditions or projects. The panels are not a diagnosis or a substitute
for the group statistical analysis.
</p>
"""

INDIVIDUAL_DETECTABILITY_TOOL_INFO = ToolInfoContent(
    key="individual_detectability",
    title="About Individual Detectability",
    html=INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML,
)

__all__ = [
    "INDIVIDUAL_DETECTABILITY_TOOL_INFO",
    "INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML",
]
