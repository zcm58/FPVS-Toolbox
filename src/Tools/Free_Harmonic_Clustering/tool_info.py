"""User-facing method information for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from Main_App.gui.components import SurfaceSize, ToolInfoContent, ToolInfoTab

PAPER_URL = "https://doi.org/10.1111/psyp.70361"
PUBLIC_REPOSITORY_URL = "https://github.com/oliver-hermann1/FPVS_Multiharmonic"

OVERVIEW_HTML = """
<h2>What This Analysis Tests</h2>
<p>
Free Harmonic Clustering Analysis compares the <b>relative distribution</b> of
an FPVS oddball response across electrodes and retained oddball harmonics. It
preserves the electrode &times; harmonic structure that is lost when harmonic
responses are first collapsed into one summed value.
</p>

<h3>Supported Designs</h3>
<ul>
  <li><b>Paired Conditions:</b> Condition A minus Condition B for the same
  complete participants, optionally within one canonical project group.</li>
  <li><b>Independent Groups:</b> Group A minus Group B for one condition.</li>
</ul>
<p>
Each run tests one ordered contrast. Positive clusters indicate A &gt; B and
negative clusters indicate A &lt; B. Set A and B directly in the setup controls;
select them in the opposite order to reverse the contrast.
</p>

<h3>Project-Bound Workflow</h3>
<p>
The tool obtains conditions, groups, participant exclusions, base and oddball
frequencies, and processed workbooks from the active project. It first prepares
and displays the frozen cohort, harmonic domain, and data shape. Permutations
run only after that review.
</p>
<p>
The analysis never changes project metadata, QC decisions, source workbooks,
or participant assignments. A successful run creates a new, non-overwriting
results folder containing a polished Excel workbook and reproducibility files.
</p>
"""

METHOD_HTML = """
<h2>Hermann-Compatible Profile</h2>
<p>
This beta is an independent clean-room implementation of the two-dimensional
sensor &times; harmonic procedure described by Hermann et al. It mirrors the
published method and public implementation where the available information is
sufficient, but it is not a copy and is not claimed to reproduce unpublished
author tensors, software state, or adjacency data exactly.
</p>

<h3>Locked Method Settings</h3>
<p>
The GUI exposes one locked, read-only cluster/permutation profile rather than
advanced statistical controls. Every completed result bundle records the full
profile and reproducibility provenance.
</p>
<ul>
  <li>10,000 whole-participant assignments by default;</li>
  <li>cluster correction across one electrode &times; harmonic family;</li>
  <li>automatic harmonic selection using strict z &gt; 3.29;</li>
  <li>raw sign-specific cluster p-values evaluated at &le; .025 in each
  direction;</li>
  <li>participant/arm L2 normalization; and</li>
  <li>a deterministic, recorded random seed.</li>
</ul>

<h3>Signal Preparation</h3>
<ol>
  <li>Read original <b>FullFFT Amplitude (uV)</b> sheets on one shared frequency
  grid and BioSemi64 sensor set.</li>
  <li>For each retained target, calculate SNR as target amplitude divided by
  the mean surrounding amplitude within &plusmn;0.1 Hz, excluding the target and
  its immediately adjacent FFT bins.</li>
  <li>L2-normalize each participant and contrast arm across the complete
  electrode &times; harmonic array.</li>
</ol>

<h3>Harmonic Domain</h3>
<p>
<b>Hermann automatic selection</b> calculates grand-spectrum z-scores after
averaging within each arm across participants and sensors, uses sample SD and
strict z &gt; 3.29, takes the highest detected oddball harmonic in either arm,
and fills through that harmonic. <b>Fixed harmonic list</b> instead lets the
researcher choose the highest included oddball harmonic and applies the same
fill-through rule. In both modes, candidates are derived from the active
project and available FFT grid, and every base-rate overlap is excluded.
</p>

<h3>Clusters and Permutations</h3>
<p>
The fixed spatial graph is a versioned 197-edge FieldTrip-style reconstruction
for BioSemi64. It was independently reconstructed for the Toolbox and is
<b>not</b> the authors' adjacency matrix. Spatial neighbors connect at the same
harmonic; all retained harmonics at one electrode are mutually adjacent.
Together, these connections define the single electrode &times; harmonic family
over which clusters are corrected.
</p>
<p>
Nodes enter positive or negative clusters at a two-sided alpha of .01. Cluster
mass is the signed sum of t values. The default 10,000 assignments permute
whole participant arrays: paired runs use sign flips and independent runs
preserve group sizes while shuffling labels. Separate positive and negative
extreme-cluster null distributions are used. Raw sign-specific cluster
p-values are evaluated at &le; .025 in each direction for a two-tailed family
alpha of .05. Monte Carlo p-values use strict extreme comparisons and the +1
correction. The recorded random seed and assignment provenance make the run
reproducible.
</p>
"""

INTERPRETATION_HTML = """
<h2>Reading the Results</h2>
<p>
Read <b>Significant Results</b> first. The primary p-value is the raw,
sign-specific Monte Carlo cluster p-value, evaluated at <b>.025 per direction</b>
for a two-tailed family alpha of .05. The doubled p-value is a secondary
two-sided presentation of the same result; it is not an additional test. The
Monte Carlo interval describes uncertainty from a finite number of random
assignments.
</p>
<p>
A positive cluster means that the normalized response is relatively stronger
for A than B at the connected electrode &times; harmonic cells; a negative cluster
means the reverse. Because of L2 normalization, this is evidence about the
<b>shape and distribution</b> of the response, not a test of total response
magnitude.
</p>

<h3>Important Limits</h3>
<ul>
  <li>Inference is for the cluster as a whole. A significant cluster does not
  make any individual electrode, harmonic, cell, or cluster boundary
  pointwise significant.</li>
  <li>The procedure provides weak/global family-wise error control for the one
  declared electrode &times; harmonic family. Separate condition runs are not
  automatically corrected as one larger family.</li>
  <li>Cluster-average effect sizes are descriptive, post-selection, and depend
  on cluster shape.</li>
  <li>A higher-harmonic effect can reflect a more complex response waveform,
  but one harmonic should not be assigned to one neural process by itself.</li>
  <li>Automatic same-data harmonic selection is faithful to the published
  workflow but remains an inferential limitation. A preregistered fixed domain
  is preferable for a confirmatory analysis.</li>
</ul>
"""

REFERENCES_HTML = f"""
<h2>References</h2>
<ul>
  <li><a href="{PAPER_URL}">Hermann, Wong Hiu Ching, and Stothart (2026),
  <i>Preserving Harmonic Structure in FPVS-Oddball: A Two-Dimensional
  Cluster-Based Permutation Approach</i></a></li>
  <li><a href="{PUBLIC_REPOSITORY_URL}">Hermann et al. public
  FPVS_Multiharmonic repository</a></li>
</ul>
<p>
FPVS Toolbox mirrors the Free Harmonic Clustering implementation described by
Hermann et al. (2026) and in the authors' public GitHub repository. All credit
for this methodology goes to the authors. Links to the paper and repository
appear above.
</p>
"""

HARMONIC_SELECTION_HTML = """
<h2>Choosing the Highest Harmonic</h2>
<p>
This control does not select one isolated frequency. It defines the upper end
of a <b>fill-through</b> domain: the analysis includes every eligible oddball
harmonic from the first through the selected highest harmonic.
</p>
<p>
The candidate list is generated from the active project's oddball frequency,
base frequency, FullFFT grid, and available upper frequency. Any oddball
harmonic that coincides with a base-rate harmonic is excluded automatically,
including an overlap below the selected upper end.
</p>
<p>
Review the included and excluded frequencies in the preparation summary before
running permutations. Before reading the FFT data, the tool verifies the
current base and oddball rates against saved provenance for the exact processed
workbook. Missing, stale, or conflicting provenance—or unavailable FFT
bins—stops preparation instead of substituting a hard-coded frequency or nearby
bin. Saved Stats harmonic selections are not reused.
</p>
"""

FREE_HARMONIC_CLUSTERING_TOOL_INFO = ToolInfoContent(
    key="free_harmonic_clustering",
    title="About Free Harmonic Clustering Analysis",
    html="",
    size=SurfaceSize(width=760, height=600, min_width=600, min_height=460),
    tabs=(
        ToolInfoTab("overview", "Overview", OVERVIEW_HTML),
        ToolInfoTab("method", "Method", METHOD_HTML),
        ToolInfoTab("interpretation", "Interpretation", INTERPRETATION_HTML),
        ToolInfoTab("references", "References", REFERENCES_HTML),
    ),
)

HARMONIC_SELECTION_TOOL_INFO = ToolInfoContent(
    key="free_harmonic_clustering_harmonic_selection",
    title="About Harmonic Fill-Through",
    html=HARMONIC_SELECTION_HTML,
    size=SurfaceSize(width=580, height=420, min_width=460, min_height=340),
)

__all__ = [
    "FREE_HARMONIC_CLUSTERING_TOOL_INFO",
    "HARMONIC_SELECTION_HTML",
    "HARMONIC_SELECTION_TOOL_INFO",
    "INTERPRETATION_HTML",
    "METHOD_HTML",
    "OVERVIEW_HTML",
    "PAPER_URL",
    "PUBLIC_REPOSITORY_URL",
    "REFERENCES_HTML",
]
