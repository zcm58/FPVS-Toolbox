"""User-facing LORETA method information text."""

from __future__ import annotations

LORETA_METHOD_INFO_HTML = """
<h2>What This Tool Is Showing</h2>
<p>
The LORETA Tool gives you a way to visualize the neural source of oddball responses in 
3D space to help combat the EEG inverse problem. There are two separate and independent methods 
deployed here: L2 minimum-norm source estimation, which predicts the origin of oddball responses 
on the cortical surface only, and eLORETA, which independently estimates the source of oddball responses
in three dimensions inside the brain. These tools are meant to be used as visual aids. 

L2 minimum norm source estimation was used in two published FPVS studies (Hauk et al., 2021; Hauk et al., 2025) 
and written about in more detail in Hauk et al. (2022). 
 
</p>

<h3>Surface Source Maps</h3>
<p>
The L2-MNE surface maps use the selected FPVS oddball harmonics and the nearby
noise bins from the FullFFT output. FPVS Toolbox estimates the target and noise
topographies in source space for each participant first, converts those maps to
source-space z-scores, and then summarizes the data. You can view the raw mean, a trimmed mean, or the median.
</p>
<p>
The FPVS Toolbox uses an fsaverage MRI brain template and then maps the participant data onto this template. This
requires some normalization from each participant, as each brain is not exactly the same, so this likely introduces
a small amount of error in each participant and in the group level estimations. 
</p>

<h3>Cluster-Based Permutation Mask</h3>
<p>
Cluster based permutation tests are widely used in statistical analysis, and these were employed in 
Hauk et al., 2021 across the group level to ensure that the group level heatmaps only display 
vertices that were significant across the entire group. Cluster based permutation tests are very conservative and 
can therefore significantly reduce the amount of painted vertices that appear on the surface or in the 
eLORETA 3D view. 

In short, FPVS Toolbox checks each source point across participants. Source
points that pass the cluster-forming threshold and touch each other are grouped
into clusters. Then the toolbox repeats the analysis with random sign flips to
ask a question: how large could the biggest cluster be if there were no
consistent group response?
</p>
<p>
Only clusters that are larger than expected under that permutation test remain
visible in the masked display. You can disable this mask if you'd like, but just be aware that 
the source map you see without the mask could be influenced by an outlier or small number of participants
across your dataset, so use caution when interpreting data without the mask. 
</p>

<h3>eLORETA Volume View</h3>
<p>
The eLORETA volume view is included as a visual estimate in template volume
space. EEG source estimation has limited spatial precision, and
using the template brains instead of participant level MRI data adds another layer of uncertainty.
Exercise caution when interpreting results from this view. 
</p>

<h3>fsaverage Anatomy</h3>
<p>
FPVS Toolbox uses MNE's fsaverage template to visualize data rather than relying on individual level MRI data. 
That makes the workflow practical and consistent across projects, but it also
means source locations are approximate. I suggest using these maps as visual aids and for descriptive figures, but 
don't rely on this data as your source of truth. 
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
