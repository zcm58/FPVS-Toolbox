"""User-facing LORETA method information text."""

from __future__ import annotations

from Main_App.gui.components import SurfaceSize, ToolInfoContent

LORETA_METHOD_INFO_HTML = """
<h2>What This Tool Is Showing</h2>
<p>
The LORETA Visualizer displays estimates of where an FPVS oddball response
could have arisen on the cortical surface or in template volume source space.
Source estimation cannot uniquely recover the true generators of scalp EEG, so
these maps should be interpreted as model-based visual aids rather than
anatomical ground truth.
</p>
<p>
The normal FPVS Toolbox workflow generates both EEG-only L2-MNE cortical and
eLORETA volume maps from signed time-domain derivatives. The default L2 method,
<code>l2_mne_hauk_source_psd_cortical_normal_v1</code>, uses the cortical-normal
orientation and matches the Hauk source estimator more closely. The current
eLORETA method, <code>eloreta_volume_hauk_source_psd_vector_norm_v1</code>, is a
Hauk-informed Toolbox extension for EEG-only fsaverage volume source space.
Neither claims to reproduce the reference study's combined EEG/MEG or
individual-MRI pipeline exactly. Older amplitude-derived maps and historical
orientation methods remain importable with explicit legacy labels.
</p>

<h3>Shared Time-Domain FPVS Method</h3>
<p>
During processing, FPVS Toolbox averages each participant's repetitions while
the EEG waveform is still signed and saves the same source-ready FIF inputs for
both methods. Each participant contributes to every canonical condition they
completed. A missing condition omits only that participant-condition input; it
does not remove the participant's completed conditions. Every group-condition
map records its own participant count and participant identities. Both builds
use the same project-selected oddball harmonics, exact FFT bins, harmonic
alignment, and neighboring-bin z-score algorithm. Their orientation and
source-amplitude calculations differ as described below. Starting from signed
waveforms avoids projecting a scalp magnitude map that has already discarded
phase and polarity.
</p>
<p>
The two maps are independent source calculations. Default L2-MNE asks MNE for
the cortical surface-normal source PSD (<code>pick_ori="normal"</code>) before
converting power to amplitude. Source Map Options can instead select the legacy
pooled-orientation method <code>l2_mne_hauk_source_psd_v1</code> to reproduce
older L2 maps. The two L2 choices retain separate method labels, provenance,
and caches.
</p>
<p>
Current eLORETA computes complex periodic-Hann coefficients at only the exact
required FPVS bins, applies the separate eLORETA volume inverse with
<code>pick_ori="vector"</code>, and combines its three complex source components
as <code>sqrt(sum(abs(Cxyz)^2))</code>. This vector norm does not depend on the
arbitrary orientation basis of a volume source. FPVS Toolbox never reuses the
L2-MNE source arrays as eLORETA values.
</p>
<p>
The normal rebuild generates both methods from the signed FIF derivatives and
does not fall back to FullFFT amplitude workbooks. If valid source-ready FIFs
already exist, maps can be rebuilt after this method update without reprocessing
the EEG.
</p>
<p>
Exact FPVS Toolbox frequency bins are intentional: a target must fall on the
processed recording's FFT grid, and the software does not silently substitute a
nearby bin. Noise uses offsets -10 through -2 and +2 through +10, removes one
minimum and one maximum, and uses population standard deviation. These Toolbox
rules are reported explicitly because they are adaptations, not a claim that
every detail matches the reference scripts.
</p>
<p>
Participant z-score maps are summarized only after the participant-level source
calculation. You can view the arithmetic mean, a 20% trimmed mean, or the median.
</p>
<p>
The Method and Display controls only select and render already-prepared values.
Surface painting, volume smoothing, MRI slices, masks, and camera choices do not
change the inverse calculation or orientation pooling.
</p>
<p>
The L2-MNE source space is strictly cortical within this workflow and is
therefore shown only on the cortical surface. The Toolbox eLORETA extension has
a separate 10 mm volume source grid bounded by the inverse model's inner-skull
BEM setup. It is not restricted to, snapped onto, or clipped by the cerebral
pial surface, and a grid location does not by itself establish a tissue label.
</p>

<h3>Cluster-Based Permutation Mask</h3>
<p>
The producer computes a one-sample t statistic across participant maps, groups
adjacent locations that pass the cluster-forming threshold, and compares each
cluster's mass with the maximum cluster mass under sign flips. New builds with small cohorts
use every sign pattern when the configured permutation count allows it; larger
runs sample patterns. For these new builds, exact tests use the null tail
proportion, while sampled tests use the plus-one correction. Their saved metadata
identifies the calculation version and the minimum attainable p-value.
Older saved masks retain their original calculation until rebuilt.
</p>
<p>
The evidence applies to a cluster, not to each vertex or its exact boundary.
The same participant-level mean-t test supplies the mask for mean, median, and
trimmed-mean displays. Separate condition masks do not test a condition
contrast. Display cutoffs are exploratory neighboring-noise z-score thresholds,
not calibrated Gaussian p-values. Disabling the mask changes display only.
</p>

<h3>eLORETA Volume View</h3>
<p>
The current eLORETA workflow preserves complex exact-bin coefficients through
MNE's eLORETA vector inverse in fsaverage volume source space, then computes a
rotation-invariant three-component amplitude. Its participant maps are
aggregated and cluster-tested with volume-source adjacency, not with the L2-MNE
cortical arrays or cortical mask. Historical
<code>eloreta_volume_hauk_source_psd_v1</code> maps remain loadable but are
labeled legacy because their pooled free-orientation result was basis-dependent.
Previously generated amplitude-derived eLORETA manifests also retain their
legacy labels; neither historical route is treated as the corrected vector-norm
result.
</p>
<p>
The 3D volume overlay uses Gaussian smoothing around the retained source-grid
locations. This display-only interpolation does not create additional
significant source locations. Only the original grid locations and values
entered the group statistics: the apparent contour boundary and the space
between grid locations are not additional tested locations or anatomical
boundaries. A one- or two-location result is still rendered as a compact 3D
volume tied to grid spacing, rather than as a screen-aligned square.
</p>
<p>
When available, the translucent 3D backdrop is derived from fsaverage's
skull-stripped whole-brain MRI; otherwise the cerebral pial surface provides
fallback orientation context. The anatomical backdrop is not a clipping
boundary: neither version defines the eLORETA source space, removes volume
locations, or changes the color scale. MRI slices are the preferred view for
anatomical localization because they show the volume estimate in direct
relation to template anatomy. The interactive 3D view is a complementary
spatial overview.
</p>

<h3>fsaverage Anatomy</h3>
<p>
FPVS Toolbox intentionally uses MNE's fsaverage template anatomy and the
canonical BioSemi64 EEG montage instead of participant MRI and coregistration
data. Both methods are EEG-only; MEG and EEG/MEG fusion are not performed. This
makes consistent source workflows available without an MRI pipeline, but
anatomical locations remain approximate. Use the maps for descriptive inference
and figures, and report the template-model limitation. The inverses also use
MNE's ad-hoc diagonal EEG noise covariance because the Toolbox workflow does
not require a separate resting/noise recording; this is a reported adaptation
of the Hauk study rather than an exact reproduction.
</p>

<h3>References And Background</h3>
<ul>
  <li><a href="https://doi.org/10.1111/psyp.13335">Sassenhagen and Draschkow (2019)</a>: limits of cluster-level localization claims.</li>
  <li><a href="https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html">SciPy permutation-test documentation</a>: exact and sampled p-values.</li>
  <li><a href="https://doi.org/10.1038/s41467-020-19160-7">Crameri et al. (2020)</a>: scientific colour communication; the viewer uses Matplotlib viridis.</li>
  <li><a href="https://doi.org/10.1016/j.neuroimage.2021.118460">Hauk et al. (2021)</a>: combined EEG/MEG FPVS source estimation for face-selective responses.</li>
  <li><a href="https://github.com/olafhauk/FPVS_sweep">Hauk FPVS_sweep repository</a>: public analysis scripts that informed the time-domain source-PSD sequence.</li>
  <li><a href="https://doi.org/10.1016/j.neuroimage.2022.119177">Hauk, Stenroos, and Treder (2022)</a>: practical guidance on what EEG/MEG source estimates can and cannot localize.</li>
  <li><a href="https://doi.org/10.1162/imag_a_00414">Hauk et al. (2025)</a>: word-selective FPVS EEG/MEG source-space analyses.</li>
  <li><a href="https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html">MNE fsaverage dataset</a>: the template anatomy files used by the visualizer.</li>
  <li><a href="https://mne.tools/stable/auto_tutorials/forward/35_eeg_no_mri.html">MNE template MRI source modeling note</a>: why template source reconstruction should not be over-interpreted.</li>
</ul>
"""

LORETA_METHOD_INFO = ToolInfoContent(
    key="loreta_method",
    title="About LORETA Source Maps",
    html=LORETA_METHOD_INFO_HTML,
    size=SurfaceSize(width=660, height=640, min_width=520, min_height=460),
)

__all__ = ["LORETA_METHOD_INFO", "LORETA_METHOD_INFO_HTML"]
