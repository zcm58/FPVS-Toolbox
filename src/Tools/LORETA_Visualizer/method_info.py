"""User-facing LORETA method information text."""

from __future__ import annotations

LORETA_METHOD_INFO_HTML = """
<h2>What This LORETA View Is Showing</h2>
<p>
The LORETA Visualizer is a way to look at prepared source-map estimates from
your FPVS data. It is meant to help you inspect the broad source-space pattern
behind the sensor-level response. It does not change your processed EEG data,
your statistics workbook, or any participant exclusions.
</p>

<h3>Surface Source Maps</h3>
<p>
The L2-MNE surface maps use the selected FPVS oddball harmonics and the nearby
noise bins from the FullFFT output. FPVS Toolbox estimates the target and noise
topographies in source space for each participant first, converts those maps to
source-space z-scores, and then makes group summaries such as the raw mean,
median, and trimmed mean.
</p>
<p>
This follows the general Hauk-style FPVS source-space workflow, but it is still
a beta toolbox implementation. In particular, FPVS Toolbox currently uses EEG
and a template fsaverage anatomy rather than each participant's own MRI.
</p>

<h3>Cluster-Based Permutation Mask</h3>
<p>
The cluster mask is a conservative display mask for group source-space z-score
maps. First, FPVS Toolbox checks each source point across participants. Source
points that pass the cluster-forming threshold and touch each other are grouped
into clusters. Then the toolbox repeats the analysis with random sign flips to
ask a simple question: how large could the biggest cluster be if there were no
consistent group response?
</p>
<p>
Only clusters that are larger than expected under that permutation test remain
visible in the masked display. This helps reduce the chance of over-reading
isolated bright source points. If no usable saved mask exists, the viewer falls
back to the manual z-score threshold. That fallback is for exploration, not a
formal source-space significance mask.
</p>

<h3>eLORETA Volume View</h3>
<p>
The eLORETA volume view is included as a visual estimate in template volume
space. It can be useful for seeing whether activity looks superficial, deep,
focal, or broad, but it should not be treated as proof that a deep structure is
the true neural source. EEG source estimation has limited spatial precision, and
template anatomy adds another layer of uncertainty.
</p>

<h3>fsaverage Anatomy</h3>
<p>
The viewer uses MNE's fsaverage template when individual MRIs are not available.
That makes the workflow practical and consistent across projects, but it also
means source locations are approximate. Use the maps as anatomical context, and
keep the sensor-space FPVS statistics as the primary analysis.
</p>

<h3>References And Background</h3>
<ul>
  <li><a href="https://doi.org/10.1016/j.neuroimage.2021.118460">Hauk et al. (2021)</a>: combined EEG/MEG FPVS source estimation for face-selective responses.</li>
  <li><a href="https://doi.org/10.1016/j.neuroimage.2022.119177">Hauk, Stenroos, and Treder (2022)</a>: practical guidance on what EEG/MEG source estimates can and cannot localize.</li>
  <li><a href="https://doi.org/10.1162/imag_a_00414">Hauk et al. (2025)</a>: word-selective FPVS EEG/MEG source-space analyses.</li>
  <li><a href="https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html">MNE fsaverage dataset</a>: the template anatomy files used by the visualizer.</li>
  <li><a href="https://mne.tools/stable/auto_tutorials/forward/35_eeg_no_mri.html">MNE template MRI source modeling note</a>: why template source reconstruction should not be over-interpreted.</li>
</ul>
"""


__all__ = ["LORETA_METHOD_INFO_HTML"]
