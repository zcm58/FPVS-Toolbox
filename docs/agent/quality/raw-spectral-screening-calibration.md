# Raw-Spectral Screening Calibration

The current raw-spectral screen is an experimental, review-only method. Its
locked v1 defaults are a 0.5-Hz lower boundary, Legacy Hann-spectrum score 250,
local-mean ratio 25, local standardized score 12, and a widespread label at
75% and at least 48 BioSemi64 scalp channels. The fixed neighborhood uses
+/-12 FFT bins, removes the target and immediate neighbors, and trims one
finite minimum and maximum. Do not describe these values as validated artifact
cutoffs or the standardized score as a normal-theory z statistic.

Before changing the claims, authority, scaling, or values, calibrate a new
method version on annotated BioSemi64 FPVS recordings spanning presentation and
oddball rates, cycle counts and durations, sampling rates, filters, 50/60-Hz
notches, populations, and artifact types. Record participant/recording splits,
labels and prevalence, threshold-selection procedure, confusion matrices with
uncertainty, dataset version/hash, code commit, environment, and performance by
protocol stratum. Keep stimulation-harmonic responses separate from artifacts.

Evaluate a correctly coherent-gain-normalized Hann amplitude alongside the
legacy `abs(rfft((x - median(x)) * hann)) * 2e6 / N` score. Adopting physical
microvolt language requires a new version and re-derived threshold. Changing
the fixed-bin neighborhood also requires a new version because its realized Hz
width changes with condition duration.

Calibration cannot override deterministic notch collisions. Validate those
against the shared spectral-eligibility resolver: a notched target is
unavailable, and a notched required QC-14 noise bin makes BCA/SNR/local-z
unavailable. The configured notch remains in place and the rest of the
recording-condition remains eligible.
