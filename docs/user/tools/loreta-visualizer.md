# LORETA Visualizer

The LORETA Visualizer helps you view beta source-space maps from FPVS Toolbox projects.

Use this tool when you want to see where an FPVS oddball response is estimated to appear in source space, instead of only reviewing electrode-level scalp plots. The visualizer can show cortical-surface maps based on L2 minimum-norm estimation (L2-MNE) and volume maps based on eLORETA.

Source estimation is an interpretive visualization step. It can help you inspect likely source-space patterns, but it should not be treated as exact anatomical proof from scalp EEG alone.

## Before You Start

Use the LORETA Visualizer after your data has been processed in FPVS Toolbox.

To use the tool, you should already have:

- a completed FPVS Toolbox project;
- processed Excel output files for your conditions;
- a Stats-ready workbook or the project outputs required by the source-map workflow;
- condition and harmonic settings that match the experiment you ran.

## What You Can Do

Use this tool to:

- review beta cortical-surface source maps for each condition;
- review beta eLORETA volume source maps;
- switch between loaded source-map methods when more than one method is available;
- compare conditions visually in source space;
- export source-map figures for review, presentations, or manuscript drafting.

## Source-Map Views

### L2-MNE Cortical Surface

The L2-MNE cortical-surface view estimates the source of the observed electrode level activity on the cortical surface.
This is useful when you want a source-space view that is aligned with the outer cortical sheet.

The L2-MNE workflow is most relevant to the FPVS source-estimation examples and methodological guidance described by
Hauk and colleagues. Hauk et al. (2021) and Hauk et al. (2025) provide FPVS examples using EEG/MEG source-space
analysis. Hauk et al. (2022) provides broader guidance on evaluating linear EEG/MEG source-estimation methods,
including L2-MNE-type methods.

### eLORETA Volume

The eLORETA volume view estimates activity in a 3D source space rather than only on the cortical surface. This can be useful when you want to inspect a volume-style source map for the same FPVS response.

eLORETA stands for exact low-resolution electromagnetic tomography. It belongs to the LORETA family of distributed EEG source-estimation methods and is designed to estimate source activity from scalp-recorded electrical signals. Because it is still a low-resolution inverse method, the result should be interpreted as an estimated source-space pattern, not a precise anatomical location.

## Inputs

The tool uses FPVS Toolbox project outputs that have already been created during processing and statistics export. When source maps are available, the visualizer loads the prepared source-map files for the selected conditions.

If source maps are not already available, the Toolbox may need to prepare them from the current project outputs before they can be displayed.

## Display Options

Depending on the loaded source-map method, you can use options such as:

- cortical surface view, a 3D interactable model of the cortical surface
- split-hemisphere cortical view, which allows you to view both left and right hemispheres simultaneously
- transparent brain mesh view, which is great for visualization of eLORETA source localization
- MRI slice view (beta) for an MRI like estimation of source localization

The available options may differ depending on whether you are viewing an L2-MNE cortical map or an eLORETA volume map.

## Outputs

The LORETA Visualizer can export source-map figures from supported views.

Use exported figures as review or presentation images unless your analysis plan specifically includes source-space reporting. If you report source-space results, cite the relevant source-estimation method and describe the workflow used to generate the maps.

## Basic Steps

1. Process your data in FPVS Toolbox.
2. Export or confirm the required statistics/project outputs.
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
