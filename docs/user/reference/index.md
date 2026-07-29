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
5. optionally apply the smart FFT Hann multi-notch line-noise filter;
6. downsample;
7. detect high-kurtosis channels and interpolate them; and
8. apply the final average reference.

The line-noise option is enabled at 60 Hz by default and can instead target
50 Hz. It requests the selected mains fundamental and two harmonics, using a
Hann-shaped FFT notch with a 0.5 Hz half-width. The toolbox applies only centers
that overlap the preceding FIR's retained frequencies and fit below the raw
Nyquist limit. For example, with a 1--100 Hz FIR it applies the 50 or 60 Hz
fundamental; the 50 Hz setting also applies the supported portion of its 100 Hz
notch, while requested components above the retained band are skipped. If the
FIR has already removed every requested center, the FFT operation is skipped.
Turning the option off bypasses this stage without changing the existing
signal-processing path.

The parameter precedent is Retter and Rossion's FPVS analysis, which reports
an FFT multi-notch with a 0.5 Hz width at three 50 Hz harmonics after a
0.1--120 Hz band-pass
([Neuropsychologia, 2016](https://doi.org/10.1016/j.neuropsychologia.2016.07.028)).
FPVS Toolbox defines that value precisely as a 0.5 Hz Hann half-width. Its smart
skip follows the same principle illustrated by the
[Letswave preprocessing guide](https://letswave.cn/tu_ch1_2): do not add a
line-frequency notch when the preceding band-pass has already excluded it.

The order matters. In particular, the FIR and any effective multi-notch
filtering occur before downsampling, and the final average reference occurs
after channel-quality handling. The toolbox then extracts epochs and writes
frequency-domain FFT-amplitude, SNR, BCA, and z-score tables.

FPVS Toolbox does not automatically apply independent component analysis (ICA)
or an equivalent component-rejection stage. Describe any artifact procedures
performed outside the toolbox separately in the study methods.

For the exact default Summed BCA harmonic rule, including the neighboring-bin
noise window and threshold, see [Statistical Analysis](../tools/statistics.md).
For the native single- and multi-group model, correction, diagnostic, and
interpretation fields that must be reported, use the
[statistical methods reporting checklist](methods-reporting-checklist.md#statistical-analysis).

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
- Van der Donck, S., Dzhelyova, M., Vettori, S., Mahdi, S. S., Claes, P.,
  Steyaert, J., & Boets, B. (2020). [Rapid neural categorization of angry and
  fearful faces is specifically impaired in boys with autism spectrum
  disorder](https://doi.org/10.1111/jcpp.13201). *Journal of Child Psychology
  and Psychiatry, 61*(9), 1019--1029.
- Vettori, S., Van der Donck, S., Dzhelyova, M., Jacques, C., Van Wesemael, T.,
  Steyaert, J., Rossion, B., & Boets, B. (2020). [Frequency-tagging
  electroencephalography of superimposed social and non-social visual
  stimulation streams reveals reduced saliency of faces in autism spectrum
  disorder](https://doi.org/10.3389/fpsyt.2020.00332). *Frontiers in
  Psychiatry, 11*, 332.
- Samaey, C., Van der Donck, S., Lecei, A., Vettori, S., Qiao, Z., van Winkel,
  R., et al. (2024). [Between faces: childhood adversity is associated with
  reduced threat-safety discrimination during facial expression processing in
  adolescence](https://doi.org/10.1186/s12916-024-03610-w). *BMC Medicine,
  22*, 382.
- Feuerriegel, D., Keage, H. A. D., Rossion, B., & Quek, G. L. (2018).
  [Immediate stimulus repetition abolishes stimulus expectation and surprise
  effects in fast periodic visual oddball
  designs](https://doi.org/10.1016/j.biopsycho.2018.09.002). *Biological
  Psychology, 138*, 110--125.
- Keil, A., Bernat, E. M., Cohen, M. X., Ding, M., Fabiani, M., Gratton, G.,
  et al. (2022). [Recommendations and publication guidelines for studies using
  frequency domain and time-frequency domain analyses of neural time
  series](https://doi.org/10.1111/psyp.14052). *Psychophysiology, 59*(5),
  e14052.

## Source-Estimation Background

Source-space figures are inverse-model estimates rather than direct anatomical
measurements. Template anatomy adds further uncertainty. Use the
[LORETA Visualizer guide](../tools/loreta-visualizer.md) for the current
tool-specific cautions. For the current time-domain L2-MNE source-PSD method,
use the
[source-PSD methods and reporting checklist](methods-reporting-checklist.md#hauk-informed-source-psd-workflow)
for the exact input, FFT-bin, neighboring-noise, and attribution requirements.

- Hauk, O., Stenroos, M., & Treder, M. S. (2022). [Towards an objective evaluation of EEG/MEG source estimation methods: The linear approach](https://doi.org/10.1016/j.neuroimage.2022.119177). *NeuroImage, 255*, 119177.
- Pascual-Marqui, R. D. (2007). [Discrete, 3D distributed, linear imaging methods of electric neuronal activity. Part 1: Exact, zero error localization](https://doi.org/10.48550/arXiv.0710.3341).

## Reporting the Toolbox

In a manuscript or preregistration, report:

- the FPVS Toolbox release or commit used;
- the raw recording format and montage;
- all preprocessing settings and the processing order above, including whether
  line-noise filtering was enabled and the selected 50 or 60 Hz mains
  frequency;
- epoch timing and trigger definitions;
- the SNR, BCA, z-score, and harmonic-selection settings used;
- ROI definitions and participant/electrode exclusions;
- any manual or external processing; and
- the exact statistical model and multiplicity correction.

Keep the generated quality-control, harmonic-selection, source-data, and
stats-ready workbooks with the analysis record. They provide the audit trail
needed to reconstruct the reported settings and plotted values.
