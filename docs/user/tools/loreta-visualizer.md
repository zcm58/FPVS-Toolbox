# LORETA Visualizer

The LORETA Visualizer helps you view beta source-space maps from FPVS Toolbox projects.

Use this tool when you want to see where an FPVS oddball response is estimated to appear in source space, instead of only reviewing electrode-level scalp plots. The visualizer can show cortical-surface maps based on L2 minimum-norm estimation (L2-MNE) and volume maps based on eLORETA.

Source estimation is an interpretive visualization step. It can help you inspect likely source-space patterns, but it should not be treated as exact anatomical proof from scalp EEG alone.

## Before You Start

Use the LORETA Visualizer after your data has been processed in FPVS Toolbox.

To use the tool, you should already have:

- a completed FPVS Toolbox project;
- valid signed source-ready FIF/JSON derivatives created during processing;
- a current saved significant-oddball-harmonic selection; and
- condition and harmonic settings that match the experiment you ran.

If valid source-ready FIFs already exist, changing the current source method or
orientation does not require reprocessing the EEG. Use Source Map Options to
rebuild the maps from those existing derivatives. Legacy amplitude-derived maps
have different workbook prerequisites and remain viewable only as explicitly
legacy/exploratory results.

## What You Can Do

Use this tool to:

- review beta cortical-surface source maps for each condition;
- review beta eLORETA volume source maps;
- switch between loaded source-map methods when more than one method is available;
- compare conditions visually in source space;
- export source-map figures for review, presentations, or manuscript drafting.

## Source-Map Views

### L2-MNE Cortical Surface

The L2-MNE cortical-surface view displays a distributed estimate that is
consistent with the observed electrode-level activity under the selected head
model, inverse-method assumptions, and regularization. It provides a
source-space view aligned with the outer cortical sheet; it does not uniquely
identify the generators of the scalp signal.

The recommended L2 setting is "Cortical normal (Hauk-style)" and is recorded as
`l2_mne_hauk_source_psd_cortical_normal_v1`. It asks MNE to estimate the
component normal to the cortical surface before converting source power to
amplitude. This matches Hauk's source estimator more closely, while retaining
the Toolbox's EEG-only fsaverage and FPVS-bin adaptations. Source Map Options
also provides "Legacy MNE pooled orientation" with method ID
`l2_mne_hauk_source_psd_v1` when you need to reproduce maps generated before
this correction.

Hauk et al. (2021) and Hauk et al. (2025) provide FPVS examples using EEG/MEG
source-space analysis. Hauk et al. (2022) provides broader guidance on
evaluating linear EEG/MEG source-estimation methods, including L2-MNE-type
methods.

### eLORETA Volume

The eLORETA volume view estimates activity in a 3D source space rather than only
on the cortical surface. This can be useful when you want to inspect a
volume-style source map for the same FPVS response.

The current method, `eloreta_volume_hauk_source_psd_vector_norm_v1`, keeps the
complex periodic-Hann coefficient at each required exact FPVS bin while MNE
applies the eLORETA inverse in all three source orientations. It then combines
the three coefficients as
`sqrt(abs(Cx)^2 + abs(Cy)^2 + abs(Cz)^2)`. This vector length is unchanged by a
rotation of the arbitrary volume-source orientation basis. The former
`eloreta_volume_hauk_source_psd_v1` method remains loadable as a historical
result, but its free-orientation pooling was basis-dependent and it is not
treated as the corrected method.

This eLORETA workflow is an FPVS Toolbox extension of Hauk's source-spectrum
sequence; it is not a claim that Hauk and colleagues implemented this exact
EEG-only fsaverage volume method. Because eLORETA is still a low-resolution
inverse method, interpret the result as an estimated source-space pattern, not
a precise anatomical location.

## Inputs

The current methods use the signed, repetition-averaged source-ready FIF files
created during processing plus the saved project harmonic selection. When
source maps are available, the visualizer loads the prepared source-map files
for the selected conditions.

If source maps are absent or use a historical orientation method, Source Map
Options can rebuild them from valid existing FIF derivatives. Reprocessing is
needed only when those derivatives are missing, stale, or invalid.

## Display Options

Depending on the loaded source-map method, you can use options such as:

- cortical surface view, a 3D interactable model of the cortical surface
- split-hemisphere cortical view, which allows you to view both left and right hemispheres simultaneously
- transparent brain mesh view for inspecting the prepared eLORETA volume estimate;
- MRI slice view (beta) for viewing that estimate against template anatomy.

The available options may differ depending on whether you are viewing an L2-MNE cortical map or an eLORETA volume map.

Display choices never change the source calculation. Surface painting, volume
smoothing, masks, camera position, and MRI slices operate on already-prepared
values; the L2 orientation choice affects only the next source-map rebuild.

## Outputs

The LORETA Visualizer can export source-map figures from supported views.

Use exported figures as review or presentation images unless your analysis plan specifically includes source-space reporting. If you report source-space results, cite the relevant source-estimation method and describe the workflow used to generate the maps.

## Basic Steps

1. Process your data in FPVS Toolbox.
2. Confirm that current source-ready derivatives and harmonic selection exist.
3. Open the LORETA Visualizer.
4. Load or generate the available source maps for the project.
5. Choose the source-map method and condition to view.
6. Adjust the display settings if needed.
7. Export figures from the selected view if needed.

## References

- Hauk, O., Rice, G. E., Volfart, A., Magnabosco, F., Lambon Ralph, M. A., & Rossion, B. (2021). Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS). *NeuroImage*, 242, 118460. <https://pubmed.ncbi.nlm.nih.gov/34363957/>
- Hauk, O., Stenroos, M., & Treder, M. S. (2022). Towards an objective evaluation of EEG/MEG source estimation methods: The linear approach. *NeuroImage*, 255, 119177. <https://doi.org/10.1016/j.neuroimage.2022.119177>
- Hauk, O., Marchive, M., Volfart, A., Schiltz, C., Rossion, B., Lambon Ralph, M. A., & Lochy, A. (2025). Word-selective EEG/MEG responses in the English language obtained with Fast Periodic Visual Stimulation (FPVS). *Imaging Neuroscience*, 3, imag_a_00414. <https://doi.org/10.1162/imag_a_00414>
- Pascual-Marqui, R. D. (2007). Discrete, 3D distributed, linear imaging methods of electric neuronal activity. Part 1: Exact, zero error localization. <https://doi.org/10.48550/arXiv.0710.3341>
- Pascual-Marqui, R. D., Lehmann, D., Koukkou, M., Kochi, K., Anderer, P., Saletu, B., Tanaka, H., Hirata, K., John, E. R., Prichep, L., Biscay-Lirio, R., & Kinoshita, T. (2011). Assessing interactions in the brain with exact low-resolution electromagnetic tomography. *Philosophical Transactions of the Royal Society A*, 369(1952), 3768-3784. <https://doi.org/10.1098/rsta.2011.0081>
