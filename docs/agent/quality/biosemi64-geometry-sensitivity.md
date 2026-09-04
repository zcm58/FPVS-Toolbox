# BioSemi64 Geometry Sensitivity Diagnostic

Status: deterministic synthetic geometry-isolation run and clean-commit release
receipt complete; representative lab-data validation remains required

Protocol: `qc15_biosemi64_geometry_sensitivity_v1`

Runner:
`scripts/manual_diagnostics/run_biosemi64_geometry_sensitivity.py`

Machine-readable receipt:
`biosemi64-geometry-sensitivity-v1-receipt.json`

## Question and result

This diagnostic asks how much FPVS output can change when the recorded signals
and bad-channel decisions are identical but MNE receives `standard_1005`
coordinates in one run and `biosemi64` coordinates in the other.

The answer is conditional and scientifically important:

- With no bad channels, the two templates produced exactly identical voltages,
  FFT amplitudes, BCA, SNR, and local z values. Merely attaching a different
  montage does not numerically change the signal. A plotted scalp map can still
  place the values at different locations because its coordinates differ.
- When interpolation was required, the template changed the repaired channel.
  Final average reference then propagated a fraction of that difference to all
  channels. Across the frozen synthetic scenarios, the largest instantaneous
  template difference was `1.4691250907842859 uV`; the largest exact-bin FFT
  amplitude difference was `0.06925538882987792 uV`, and the largest BCA
  difference was `0.06768379924659418 uV`.
- The largest SNR difference was `0.3221100040671585`, and the largest local-z
  difference was `1.326933211492804`. Six local-z threshold decisions differed
  across both reported stages. Five occurred after final average reference and
  one occurred in the intermediate pre-reference result.

This supports treating the montage correction as a processing-identity change
for recordings with interpolation or geometry-dependent channel decisions. It
does not estimate the size or prevalence of changes in the lab's historical
datasets. The synthetic results also do not show that `biosemi64` interpolation
has lower numerical error in every possible field. Its scientific justification
is that it represents the supported BioSemi cap instead of a different generic
10-05 template.

## Frozen method

The default run generated `40 s` of deterministic 64-channel data at `256 Hz`
with random seed `150064`. Smooth spatial fields were defined on BioSemi64
locations, then combined with spatially correlated 1/f-like background activity
and a small sensor-local noise term. This choice represents signals sampled at
the supported cap locations; it necessarily remains an idealized model.

The nine prespecified cases were:

| Case | Fixed bad channels |
| --- | --- |
| Zero-bad control | none |
| Isolated frontal | `Fp1` |
| Isolated temporal | `T7` |
| Isolated central | `Cz` |
| Isolated posterior | `Oz` |
| Frontal cluster | `Fp1`, `AF7`, `AF3` |
| Temporal cluster | `FT7`, `T7`, `TP7` |
| Central cluster | `C3`, `Cz`, `C4` |
| Posterior cluster | `PO7`, `Oz`, `PO8` |

Each case used the same samples and same bad-channel list in both branches. The
runner mirrored the production repair call: MNE EEG spherical-spline
interpolation, automatic sphere origin, `reset_bads=True`, followed by an
explicit average reference. MNE documents that EEG interpolation uses sensor
locations to construct its spherical-spline mapping, so coordinate choice is a
direct numerical input to the repaired channel
([MNE interpolation implementation](https://mne.tools/stable/documentation/implementation.html),
[MNE `Raw.interpolate_bads`](https://mne.tools/stable/generated/mne.io.Raw.html#mne.io.Raw.interpolate_bads)).

Exact target bins were required at `1.2`, `2.4`, `3.6`, `4.8`, and `7.2 Hz`.
FFT amplitude used the toolbox scaling `abs(fft) / N * 2`. BCA, SNR, and local z
used the production noise helper: ±10 bins, excluding the target and immediate
neighbors, dropping one finite minimum and maximum, and using population SD.
The reported threshold checks were `z > 1.64` and `z > 3.29`; these crossings
are sensitivity indicators, not participant- or group-level conclusions.

## Coordinate difference

MNE lists `standard_1005` as the 343-position international 10-05 montage and
`biosemi64` as the 64-electrode BioSemi cap
([MNE sensor-location guide](https://mne.tools/stable/auto_tutorials/intro/40_sensor_locations.html)).
BioSemi describes its standard 64-channel cap as a 10/20 layout and publishes
its cap coordinates
([BioSemi headcap specification](https://www.biosemi.com/headcap.htm)).

After MNE transformed both templates to head coordinates, corresponding labels
differed by `5.939871202208048` to `30.97100732574205 mm`, with a median of
`23.513489101629535 mm`. Direction relative to each template's automatically
fitted sphere origin differed by `1.744643869197931` to
`14.10722996447578 degrees`, with a median of `7.381045016664665 degrees`.
These values describe template geometry, not participant-specific placement
error.

The fitted spheres were:

| Montage | Radius | Head-coordinate origin `(x, y, z)` in meters |
| --- | ---: | --- |
| `standard_1005` | `0.09618853186735807 m` | `(-0.0008060181548090376, 0.014437717016407947, 0.04313286033975594)` |
| `biosemi64` | `0.09499996139641832 m` | `(0.00000003124776161121921, -0.000000021636193662711604, 0.04014887477400841)` |

## Final average-referenced differences by case

| Case | Scalp RMS difference (uV) | Maximum sample difference (uV) | Maximum FFT difference (uV) | Maximum BCA difference (uV) | Maximum SNR difference | Maximum local-z difference | Threshold changes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Zero-bad control | `0` | `0` | `0` | `0` | `0` | `0` | `0` |
| Isolated frontal | `0.019195010` | `0.575307196` | `0.008032403` | `0.009177166` | `0.057937154` | `0.151866387` | `0` |
| Isolated temporal | `0.011756413` | `0.453256733` | `0.008421866` | `0.011116982` | `0.077316115` | `0.169118226` | `0` |
| Isolated central | `0.006215294` | `0.197102480` | `0.007900262` | `0.010015852` | `0.065515438` | `0.162841531` | `0` |
| Isolated posterior | `0.013689588` | `0.409887290` | `0.068203816` | `0.065422830` | `0.322110004` | `1.326933211` | `0` |
| Frontal cluster | `0.059172980` | `1.441776233` | `0.028812549` | `0.023210982` | `0.172326701` | `0.395915198` | `1` |
| Temporal cluster | `0.030431472` | `0.681786170` | `0.027348101` | `0.032758595` | `0.169236259` | `0.515780775` | `1` |
| Central cluster | `0.014043077` | `0.270204221` | `0.011375145` | `0.009219325` | `0.060735615` | `0.151718451` | `1` |
| Posterior cluster | `0.017487150` | `0.419787160` | `0.061139472` | `0.058190509` | `0.269372624` | `1.145039180` | `2` |

The final-stage threshold changes were all close to the boundary:

| Case | Channel | Target | Threshold | `standard_1005` z / decision | `biosemi64` z / decision |
| --- | --- | ---: | ---: | --- | --- |
| Frontal cluster | `FCz` | `4.8 Hz` | `1.64` | `1.631439253` / false | `1.649811868` / true |
| Temporal cluster | `CP2` | `1.2 Hz` | `1.64` | `1.641356250` / true | `1.614073913` / false |
| Central cluster | `C4` | `1.2 Hz` | `1.64` | `1.640586959` / true | `1.562693535` / false |
| Posterior cluster | `P9` | `1.2 Hz` | `1.64` | `1.627056477` / false | `1.647165916` / true |
| Posterior cluster | `F1` | `2.4 Hz` | `1.64` | `1.635151606` / false | `1.650330086` / true |

The sixth crossing occurred before average reference for interpolated `PO8` at
`3.6 Hz` and threshold `3.29`: `3.154460400` under `standard_1005` versus
`3.294699104` under `biosemi64`.

## What this evidence supports

The zero-bad control establishes that interpolation is the route by which the
montage changes numeric EEG results in this diagnostic. After repair, average
reference spreads the bad channel's changed estimate across the scalp. This is
why several final threshold crossings occurred at channels that were not
themselves interpolated.

The result makes historical compatibility conditional. A recording with no
interpolation and no geometry-dependent channel-selection rule should retain
the same numerical time series and spectra, although its scalp-map coordinates
were wrong. A recording with one or more interpolated channels can have changed
time series, topographies, FFT/BCA/SNR/local-z values, and near-threshold
decisions. A geometry-dependent automatic detector can also nominate a
different set of channels, which this fixed-decision study intentionally did
not test.

Using the BioSemi64 geometry is scientifically defensible for the currently
supported BioSemi ActiveTwo 64 cap. It aligns the numerical interpolation and
map coordinates with the supported acquisition layout. CMS and DRL are part of
BioSemi's feedback/reference system rather than the 64 measuring-channel cap
geometry; BioSemi explains that saved signals are referenced in analysis
software and describes average reference as one common choice
([BioSemi CMS/DRL explanation](https://www.biosemi.com/faq/cms%26drl.htm)).

## Required representative-data follow-up

This run is a reproducible sensitivity demonstration, not external validation.
Before making claims about prior datasets, rerun representative lab recordings
with identical analyzed intervals and frozen bad-channel decisions under both
templates, then run the complete pipeline with each geometry-dependent detector
enabled. Cover the observed interpolation-count distribution and report changes
by participant and condition in:

1. interpolated and final average-referenced signals;
2. channel nominations and successful interpolation sets;
3. FullFFT, BCA, SNR, local z, and harmonic inclusion;
4. scalp maps and participant summaries; and
5. group-level estimates and inferential decisions.

Do not pool legacy and BioSemi64 outputs in this comparison. The purpose is to
identify which historical participant-condition outputs need reprocessing and
whether any scientific conclusions change.

## Reproduction and artifacts

Run from the repository root with its managed environment:

```console
.venv/Scripts/python.exe scripts/manual_diagnostics/run_biosemi64_geometry_sensitivity.py \
  --output-dir .codex-tmp/qc15-biosemi64-sensitivity-v1
```

The runner writes:

- `summary.json`, including protocol, runtime, limitations, scenario summaries,
  and SHA-256 hashes;
- `coordinate_differences.csv`;
- `time_domain_differences.csv`;
- `target_metrics.csv`, containing absolute FullFFT/BCA/SNR/local-z values for
  every montage, stage, channel, and exact target;
- `target_metric_differences.csv`; and
- `threshold_decision_changes.csv`.

The reviewed synthetic result fingerprint is
`fc776d270b54fd6bad2fca8b1bcae0da51a8a082b0979e58b7128f6f928c76b5`.
It ran with Python `3.13.9`, NumPy `2.3.1`, and MNE `1.9.0`. The receipt records
the exact runner and production noise-helper hashes. The release receipt was
regenerated from clean tracked commit
`c261996ed05d36c720d04c8b2026cb89e2973cd2` and records
`git_worktree_dirty: false`.

For a bounded check of one real recording, pass `--input-bdf` and an explicit
canonical `--bad-channels` list (or `none`). The mode rejects A/B labels,
incomplete anatomical labels, and ordinal inference. It analyzes only the
caller-selected interval and does not discover or modify a project.
