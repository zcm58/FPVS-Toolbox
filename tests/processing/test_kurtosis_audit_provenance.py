from __future__ import annotations

import numpy as np

from Main_App.diagnostics.audit import end_preproc_audit


class _RawStub:
    def __init__(self) -> None:
        self.info = {
            "sfreq": 256.0,
            "lowpass": 50.0,
            "highpass": 0.1,
            "bads": [],
        }
        self.ch_names = ["Fp1", "Fp2", "Status"]
        self.n_times = 8

    def get_channel_types(self) -> list[str]:
        return ["eeg", "eeg", "stim"]

    def get_data(
        self,
        *,
        picks: list[int],
        start: int,
        stop: int,
    ) -> np.ndarray:
        del start
        return np.zeros((len(picks), stop), dtype=np.float64)


def test_end_audit_preserves_kurtosis_evidence_decisions_and_separate_states():
    evidence = {"method_version": "method-v1", "fingerprint": "a" * 64}
    decision_plan = {
        "authority_policy_version": "policy-v1",
        "fingerprint": "b" * 64,
    }
    params = {
        "_fpvs_kurtosis_bad_channels": ["Fp1", "Fp2"],
        "_fpvs_kurtosis_review_required_channels": ["Fp1"],
        "_fpvs_kurtosis_corroborated_channels": [],
        "_fpvs_kurtosis_user_approved_channels": ["Fp2"],
        "_fpvs_kurtosis_user_rejected_channels": ["Fp1"],
        "_fpvs_kurtosis_qc_evidence": evidence,
        "_fpvs_kurtosis_decision_plan": decision_plan,
        "_fpvs_interpolated_channels": ["Fp2"],
        "stim_channel": "Status",
    }

    audit = end_preproc_audit(
        _RawStub(),
        params,
        filename="P01.bdf",
        events_info={"stim_channel": "Status", "n_events": 1},
        n_rejected=2,
    )

    assert audit["kurtosis_candidate_channels"] == ["Fp1", "Fp2"]
    assert audit["kurtosis_review_required_channels"] == ["Fp1"]
    assert audit["kurtosis_corroborated_channels"] == []
    assert audit["kurtosis_user_approved_channels"] == ["Fp2"]
    assert audit["kurtosis_user_rejected_channels"] == ["Fp1"]
    assert audit["kurtosis_qc_evidence"] == evidence
    assert audit["kurtosis_decision_plan"] == decision_plan
    assert audit["interpolated_channels"] == ["Fp2"]


def test_end_audit_uses_empty_structures_when_kurtosis_was_not_evaluated():
    audit = end_preproc_audit(
        _RawStub(),
        {"stim_channel": "Status"},
        filename="P01.bdf",
    )

    assert audit["kurtosis_candidate_channels"] == []
    assert audit["kurtosis_qc_evidence"] == {}
    assert audit["kurtosis_decision_plan"] == {}
