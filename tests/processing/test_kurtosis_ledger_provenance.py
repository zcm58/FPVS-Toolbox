from Main_App.processing.processing_ledger import _kurtosis_qc_payload


def test_kurtosis_ledger_payload_keeps_evidence_authority_and_outcomes_separate():
    evidence = {"method_version": "method-v1", "fingerprint": "a" * 64}
    plan = {"authority_policy_version": "policy-v1", "fingerprint": "b" * 64}

    payload = _kurtosis_qc_payload(
        {
            "kurtosis_qc_evidence": evidence,
            "kurtosis_decision_plan": plan,
            "kurtosis_bad_channels": ["Fp1", "Fp2"],
            "kurtosis_review_required_channels": ["Fp1"],
            "kurtosis_corroborated_channels": [],
            "kurtosis_user_approved_channels": ["Fp2"],
            "kurtosis_user_rejected_channels": ["Fp1"],
            "interpolated_channels": ["Fp2"],
        }
    )

    assert payload == {
        "kurtosis_qc_evidence": evidence,
        "kurtosis_decision_plan": plan,
        "kurtosis_candidate_channels": ["Fp1", "Fp2"],
        "kurtosis_review_required_channels": ["Fp1"],
        "kurtosis_corroborated_channels": [],
        "kurtosis_user_approved_channels": ["Fp2"],
        "kurtosis_user_rejected_channels": ["Fp1"],
    }


def test_kurtosis_ledger_payload_does_not_invent_legacy_evidence():
    assert _kurtosis_qc_payload(None) == {
        "kurtosis_qc_evidence": {},
        "kurtosis_decision_plan": {},
        "kurtosis_candidate_channels": [],
        "kurtosis_review_required_channels": [],
        "kurtosis_corroborated_channels": [],
        "kurtosis_user_approved_channels": [],
        "kurtosis_user_rejected_channels": [],
    }
