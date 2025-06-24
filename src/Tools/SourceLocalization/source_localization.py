import numpy as np
import mne


def extract_cycles(epochs: mne.Epochs, oddball_freq: float) -> mne.Epochs:
    """Segment epochs into single oddball cycles."""
    if oddball_freq <= 0:
        raise ValueError("oddball_freq must be positive")
    cycle_dur = 1.0 / oddball_freq
    sfreq = epochs.info["sfreq"]
    n_samples = int(round(cycle_dur * sfreq))
    data = []
    for ep in epochs.get_data():
        n_cycles = ep.shape[1] // n_samples
        for c in range(n_cycles):
            start = c * n_samples
            stop = start + n_samples
            data.append(ep[:, start:stop])
    data = np.array(data)
    return mne.EpochsArray(data, epochs.info, tmin=0.0)


def average_cycles(cycle_epochs: mne.Epochs) -> mne.Evoked:
    """Return an Evoked obtained by averaging cycle epochs."""
    return cycle_epochs.average()


def reconstruct_harmonics(evoked: mne.Evoked, harmonics: list[float]) -> mne.Evoked:
    """Reconstruct an evoked signal using only the specified harmonic frequencies."""
    sfreq = evoked.info["sfreq"]
    data = np.fft.fft(evoked.data)
    freqs = np.fft.fftfreq(evoked.data.shape[1], d=1.0 / sfreq)
    mask = np.zeros_like(freqs, dtype=bool)
    tol = sfreq / evoked.data.shape[1]
    for h in harmonics:
        mask |= np.isclose(freqs, h, atol=tol)
        mask |= np.isclose(freqs, -h, atol=tol)
    data[:, ~mask] = 0
    filtered = np.fft.ifft(data).real
    return mne.EvokedArray(filtered, evoked.info, tmin=evoked.times[0])


def build_inverse_operator(evoked: mne.Evoked, subjects_dir: str) -> mne.minimum_norm.InverseOperator:
    """Construct an inverse operator for the given evoked data."""
    subject = "fsaverage"
    src = mne.setup_source_space(subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False)
    model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
    bem = mne.make_bem_solution(model)
    fwd = mne.make_forward_solution(evoked.info, trans="fsaverage", src=src, bem=bem, eeg=True)
    noise_cov = mne.make_ad_hoc_cov(evoked.info)
    return mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)


def apply_sloreta(evoked: mne.Evoked, inv: mne.minimum_norm.InverseOperator, snr: float) -> mne.SourceEstimate:
    """Apply sLORETA to evoked data using the provided inverse operator."""
    lambda2 = 1.0 / (snr ** 2)
    return mne.minimum_norm.apply_inverse(evoked, inv, method="sLORETA", lambda2=lambda2)
