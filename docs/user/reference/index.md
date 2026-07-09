# Methods and References

FPVS Toolbox implements an opinionated processing workflow for frequency-tagged
EEG. This page identifies the current method contract and provides stable links
to the publications cited by the application and tool guides.

## Processing Contract

For raw EEG preprocessing, the active order is:

1. apply the initial reference;
2. drop the reference channels;
3. optionally limit channels while preserving the stimulation channel;
4. apply the configured FIR filter;
5. downsample;
6. detect high-kurtosis channels and interpolate them; and
7. apply the final average reference.

The order matters. In particular, filtering occurs before downsampling, and the
final average reference occurs after channel-quality handling. The toolbox then
extracts epochs and writes frequency-domain FFT-amplitude, SNR, BCA, and z-score
tables.

FPVS Toolbox does not automatically apply independent component analysis (ICA)
or an equivalent component-rejection stage. Describe any artifact procedures
performed outside the toolbox separately in the study methods.

For the exact default Summed BCA harmonic rule, including the neighboring-bin
noise window and threshold, see [Statistical Analysis](../tools/statistics.md).

## Core FPVS and Frequency-Domain Studies

- Retter, T. L., & Rossion, B. (2016). [Visual adaptation provides objective electrophysiological evidence of facial identity discrimination](https://doi.org/10.1016/j.cortex.2015.11.025). *Cortex, 80*, 35–50.
- Rossion, B., Retter, T. L., & Liu-Shuang, J. (2020). [Understanding human individuation of unfamiliar faces with oddball fast periodic visual stimulation and electroencephalography](https://doi.org/10.1111/ejn.14865). *European Journal of Neuroscience, 52*(10), 4283–4344.
- Volfart, A., Rice, G. E., Lambon Ralph, M. A., & Rossion, B. (2021). [Implicit, automatic semantic word categorisation in the left occipito-temporal cortex as revealed by fast periodic visual stimulation](https://doi.org/10.1016/j.neuroimage.2021.118228). *NeuroImage, 238*, 118228.
- Hauk, O., Rice, G. E., Volfart, A., Magnabosco, F., Lambon Ralph, M. A., & Rossion, B. (2021). [Face-selective responses in combined EEG/MEG recordings with fast periodic visual stimulation (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*, 118460.
- David, J., Quenon, L., Hanseeuw, B., Ivanoiu, A., Volfart, A., Koessler, L., & Rossion, B. (2025). [An objective and sensitive electrophysiological marker of word semantic categorization impairment in Alzheimer's disease](https://doi.org/10.1016/j.clinph.2024.12.018). *Clinical Neurophysiology, 170*, 98–109.
- Hauk, O., Marchive, M., Volfart, A., Schiltz, C., Rossion, B., Lambon Ralph, M. A., & Lochy, A. (2025). [Word-selective EEG/MEG responses in the English language obtained with fast periodic visual stimulation (FPVS)](https://doi.org/10.1162/imag_a_00414). *Imaging Neuroscience, 3*, imag_a_00414.

## Toolbox-Related Applied Studies

These studies illustrate FPVS analysis and reporting choices used in the
toolbox's current research context. They do not validate every toolbox option or
turn exploratory tools into confirmatory analyses.

- Vandenheever, D., Davidson, H., Kemp, J., Murphy, Z., Kujawa, A., Shi, J., Nadorff, M. R., Bates-Brantley, K., & Sidwell, M. (2025). [Exploring facial expression processing with fast periodic visual stimulation and diverse stimuli](https://doi.org/10.1016/j.bandc.2025.106338). *Brain and Cognition, 189*, 106338.
- Vandenheever, D., Davidson, H., Kemp, J., Murphy, Z., Kujawa, A., Shi, J., Nadorff, M. R., Bates-Brantley, K., & Sidwell, M. (2025). [Preliminary evidence for anxiety-linked neural sensitivity to emotional faces using fast periodic visual stimulation](https://doi.org/10.1016/j.ijpsycho.2025.113212). *International Journal of Psychophysiology, 214*, 113212.

## Source-Estimation Background

Source-space figures are inverse-model estimates rather than direct anatomical
measurements. Template anatomy adds further uncertainty. Use the
[LORETA Visualizer guide](../tools/loreta-visualizer.md) for the current
tool-specific cautions.

- Hauk, O., Stenroos, M., & Treder, M. S. (2022). [Towards an objective evaluation of EEG/MEG source estimation methods: The linear approach](https://doi.org/10.1016/j.neuroimage.2022.119177). *NeuroImage, 255*, 119177.
- Pascual-Marqui, R. D. (2007). [Discrete, 3D distributed, linear imaging methods of electric neuronal activity. Part 1: Exact, zero error localization](https://doi.org/10.48550/arXiv.0710.3341).

## Reporting the Toolbox

In a manuscript or preregistration, report:

- the FPVS Toolbox release or commit used;
- the raw recording format and montage;
- all preprocessing settings and the processing order above;
- epoch timing and trigger definitions;
- the SNR, BCA, z-score, and harmonic-selection settings used;
- ROI definitions and participant/electrode exclusions;
- any manual or external processing; and
- the exact statistical model and multiplicity correction.

Keep the generated quality-control, harmonic-selection, source-data, and
stats-ready workbooks with the analysis record. They provide the audit trail
needed to reconstruct the reported settings and plotted values.
