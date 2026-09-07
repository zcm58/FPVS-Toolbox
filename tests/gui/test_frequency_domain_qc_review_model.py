from __future__ import annotations

from copy import deepcopy

import pytest

from Main_App.gui.frequency_domain_qc_review_model import (
    electrode_group_key,
    electrode_groups,
    finding_section,
)


def _electrode_finding(**values: object) -> dict[str, object]:
    return {
        "participant_id": "P26",
        "condition": "Neutral Happy",
        "electrode": "O2",
        "finding_type": "absolute_electrode_summed_bca",
        "finding_fingerprint": "happy-o2",
        **values,
    }


@pytest.mark.parametrize(
    "item, expected",
    [
        (_electrode_finding(), "electrode"),
        ({"roi": "ROT", "finding_type": "cohort_relative_summed_bca_context"}, "roi"),
        (_electrode_finding(finding_type="prior_outcome_informed_exclusion_reconfirmation"), "electrode"),
        ({"roi": "O2", "electrode": "", "finding_type": "prior_outcome_informed_exclusion_reconfirmation"}, "roi"),
        ({"electrode": "O2", "roi": "O2"}, "other"),
        ({"electrode": " ", "roi": None}, "other"),
    ],
)
def test_sections_follow_target_identity_including_reconfirmed_findings(item, expected):
    assert finding_section(item) == expected


def test_same_electrode_across_conditions_groups_only_existing_electrode_findings():
    findings = [
        _electrode_finding(),
        {"participant_id": "P26", "condition": "Neutral Happy", "roi": "O2",
         "finding_fingerprint": "happy-roi"},
        _electrode_finding(condition="Pos Val", finding_fingerprint="positive-o2"),
        _electrode_finding(electrode="CP4", finding_fingerprint="happy-cp4"),
        _electrode_finding(condition="Erotic", finding_fingerprint="erotic-o2",
                           finding_type="prior_outcome_informed_exclusion_reconfirmation"),
    ]
    original = deepcopy(findings)

    groups = electrode_groups(findings, "participant")

    assert list(groups.items()) == [
        (("P26", "", "O2"), (0, 2, 4)),
        (("P26", "", "CP4"), (3,)),
    ]
    assert findings == original


@pytest.mark.parametrize("scope", ["participant", "recording"])
def test_bulk_groups_never_cross_participants_or_recordings(scope):
    findings = [
        _electrode_finding(recording_id="P26-visit1", session_id="baseline", visit_index=1),
        _electrode_finding(recording_id="P26-visit2", session_id="follow-up", visit_index=2,
                           finding_fingerprint="visit2-o2"),
        _electrode_finding(participant_id="P47", recording_id="P47-visit1",
                           finding_fingerprint="p47-o2"),
        _electrode_finding(recording_id="P26-visit1", session_id="baseline", visit_index=1,
                           condition="Pos Val", finding_fingerprint="positive-o2"),
    ]

    assert electrode_groups(findings, scope) == {
        ("P26", "P26-visit1", "O2"): (0, 3),
        ("P26", "P26-visit2", "O2"): (1,),
        ("P47", "P47-visit1", "O2"): (2,),
    }


@pytest.mark.parametrize(
    "values, scope",
    [
        ({"participant_id": ""}, "participant"),
        ({"condition": " "}, "participant"),
        ({"finding_fingerprint": None}, "participant"),
        ({"electrode": ""}, "participant"),
        ({"roi": "ROT"}, "participant"),
        ({}, "recording"),
        ({"recording_id": " "}, "recording"),
        ({}, "unknown"),
    ],
)
def test_incomplete_or_ambiguous_findings_cannot_receive_bulk_choices(values, scope):
    finding = _electrode_finding(**values)

    assert electrode_group_key(finding, scope) is None
    assert electrode_groups([finding], scope) == {}


def test_grouping_preserves_exact_report_identity_spelling():
    findings = [
        _electrode_finding(),
        _electrode_finding(participant_id="p26", finding_fingerprint="other-p26"),
        _electrode_finding(electrode="o2", finding_fingerprint="other-o2"),
    ]

    assert list(electrode_groups(findings, "participant")) == [
        ("P26", "", "O2"), ("p26", "", "O2"), ("P26", "", "o2"),
    ]
