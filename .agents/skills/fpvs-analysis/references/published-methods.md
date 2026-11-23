# Published FPVS analysis methods

This targeted review sampled primary studies published in 2024–2026, with an
earlier crossover example. Searches combined *fast periodic visual stimulation*,
*frequency tagging*, and *FPVS EEG* with *group*, *linear mixed*, *ROI*,
*repeated session*, *reliability*, and *harmonic*. The examples below come from
article methods and, where specified, the corresponding results or tables.
Use them as design precedents. This was a methods sample, so inclusion does
not estimate how often the field uses each method.

## Groups, conditions and ROIs

| Study and section | What the authors did | What to reuse or check |
| --- | --- | --- |
| **Samaey et al. (2024)**, *BMC Medicine*, EEG and Statistical analysis | Separate baseline-corrected base and oddball responses. Modeled within-participant Expression and ROI, between-participant childhood adversity group or continuous exposure, and age and gender. Used participant intercepts with an expression slope for oddball and ROI slope for base, Kenward–Roger degrees of freedom, and Bonferroni post hocs. | Preserve the study's response and grouping structure. Their MAD-based trimming and treatment of continuous exposure in post hocs are study-specific. [Full article](https://link.springer.com/article/10.1186/s12916-024-03610-w) |
| **Qiao et al. (2025)**, *Social Cognitive and Affective Neuroscience*, Statistical analysis | Used a participant intercept and `age + sex + ROI + Group * Expression` for standardized oddball response. Fitted separate symptom and adversity models within the clinical group. Used Tukey-adjusted `emmeans` follow-ups. | A covariate-adjusted group-by-expression model can answer a different question from an exposure association within one group. Record the endpoint scale and justify each covariate. [Full article](https://pmc.ncbi.nlm.nih.gov/articles/PMC12596126/) |
| **Gigleux et al. (2026)**, *Brain and Cognition*, coarse and fine discrimination analyses | Used summed BCA in mixed-design ANOVA. The coarse analysis used Condition × ROI × Group and the fine analysis used Condition × Group in a selected left ROI, with a both-ROI sensitivity. Direct group tests and one-sample detection tests answered separate questions. | A condition-specific group difference or a group-by-condition interaction needs a direct contrast. A study-chosen ROI and its sensitivity belong in the report. [Full article](https://orbilu.uni.lu/bitstream/10993/68248/1/GigleuxVanDeWalleDeGhelckeSchiltzRossin_Brain%26Cog_26_%28Lang_Dyslexia_10yo_Dvp_FPVS%29.pdf) |

## Visits, repeated contrasts and reliability

| Study and section | What the authors did | What to reuse or check |
| --- | --- | --- |
| **Barillon, Schiltz and Lochy (2025)**, *Frontiers in Human Neuroscience*, EEG processing and §4.3 | Treated pre/post Session and learning Method as crossed factors for summed oddball amplitude in a left occipitotemporal ROI. Used an LMM and estimated marginal comparisons. Used a common harmonic set across sessions and conditions, excluding the base overlap, and analyzed unlearned and known-word controls. | Test differential change using Session × Method and defined fitted contrasts. The learning design and control conditions inform interpretation. [Full article](https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2025.1647925/full) |
| **Nguyen et al. (2026)**, *eNeuro*, Significant frequency and harmonics analysis and Implicit learning | Compared Control and Mugshot using a paired test on a scalp-aggregated oddball SNR summary, with a paired-difference bootstrap. Looked at cumulative trial blocks as additional comparisons and used paired sensor-cluster analyses. | Simple paired inference is appropriate for a single matched summary. Cumulative blocks share trials and are dependent. Report SNR and BCA as distinct endpoints. [Full article](https://pmc.ncbi.nlm.nih.gov/articles/PMC13583328/) |
| **Bettoni et al. (2026)**, *Scientific Reports*, Statistical analysis | Used BCA group and ROI models with participant intercepts. Modeled linear and quadratic trends over twelve 10-second segments using participant intercepts and slopes, reusing the 120-second harmonic choices for shorter segments. | Correlated segments within a run require participant-aware inference. Segment trends and visit trends have different designs. This example selected harmonics by ROI and group, so check the measurement definition before adopting its group comparison. [Full article](https://pmc.ncbi.nlm.nih.gov/articles/PMC12804873/) |
| **Stothart et al. (2025)**, *Brain Communications*, reliability methods and Table 5 | Compared Fastball measurements at baseline and one year in healthy older adults. Reported two-way mixed ICCs with CIs for absolute agreement and consistency, and distinguished one recording from the average of recordings. | State which repeatability property and measurement count matter for the intended use. Identify who returned for retest. [Full article](https://doi.org/10.1093/braincomms/fcaf279) |
| **Van der Donck et al. (2022)**, *Psychophysiology*, Statistical analyses | Used a randomized crossover for oxytocin and placebo. Modeled BCA with Treatment × Emotion × ROI, participant intercepts and slopes, evaluated order, and used Tukey-adjusted fitted contrasts. | Crossover analysis depends on treatment sequence, period and carryover assumptions. Treat fixed-order pre/post findings as visit differences unless the design identifies a treatment effect. [Full article](https://onlinelibrary.wiley.com/doi/10.1111/psyp.14026) |

## Spectral summaries, topography and individual detection

| Study and section | What the authors did | What to reuse or check |
| --- | --- | --- |
| **Hermann et al. (2026)**, *Psychophysiology*, §§3.5–3.6 | Computed local spectral statistics in a ±0.1 Hz window, skipped adjacent bins and base overlaps, and selected a common harmonic range using condition grand averages. L2-normalized SNR per participant and condition for distribution comparisons, then compared paired cluster tests on sensor-only summaries and sensor × harmonic data. | Normalized topography and raw magnitude are different outcomes. Whole-scalp inference needs a design-aware exchange scheme and joint correction. The cluster inference concerns the cluster statistic. It does not establish significance at every constituent sensor or harmonic. This study's SNR normalization and clustering differ from Toolbox BCA exports and FHC. [Full article](https://onlinelibrary.wiley.com/doi/full/10.1111/psyp.70361) |
| **Hauk et al. (2025)**, *Imaging Neuroscience*, §2.5.2 and Figure 6 | Used fixed candidate harmonics with base-overlap exclusions, summed aligned FFT windows before applying local baseline and Z scoring, and selected EEG laterality sensors from earlier overlap evidence. Reported group and individual detection separately. | Specify the order of operations and how sensors were set. Group-level response evidence alone does not establish a calibrated individual detection rule. [Full article](https://doi.org/10.1162/imag_a_00414) |

## Implications for agent-run analysis

- Common practice in this sample was to preserve base and oddball as separate
  responses, use a prespecified or documented ROI, and quantify responses
  over selected non-overlapping oddball harmonics. Neighboring-bin definitions,
  cutoffs, which data selected the harmonics, and final scale varied.
- Studies handled repeated observations with paired summaries, repeated-measures
  ANOVA, or participant-aware LMMs. Covariate-adjusted models and random
  slopes were justified within particular study designs. The multiplicity
  correction and model test must match the stated family and backend.
- A priori ROI inference and exploratory sensor × harmonic inference answer
  different questions. Frequency-domain reporting guidance gives additional
  context for documenting selection, correction, and data handling.
  [Keil et al. (2022)](https://onlinelibrary.wiley.com/doi/10.1111/psyp.14052)
- The [Toolbox Stats contract](../../../../docs/agent/architecture/statistics-tools.md#relationship-to-published-fpvs-statistics)
  documents where native analyses align with published methods and where
  Toolbox uses its own profiles, inference, and families.
