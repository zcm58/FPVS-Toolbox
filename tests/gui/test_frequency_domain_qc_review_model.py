from __future__ import annotations

from copy import deepcopy
from itertools import product

import pytest

from Main_App.gui.frequency_domain_qc_review_model import (
    can_interpolate_finding,
    decision_consequence,
    electrode_group_key,
    electrode_groups,
    finding_section,
    review_attention,
)
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
    DECISION_RETAIN,
    REVIEW_DECISIONS,
    validate_frequency_domain_qc_review_decisions,
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
        ({"roi": "ROT", "finding_type": "cohort_relative_summed_bca_context"}, None),
        (_electrode_finding(finding_type="prior_outcome_informed_exclusion_reconfirmation"), "electrode"),
        (_electrode_finding(evidence={"finding_type": "cohort_relative_summed_bca_context"}), "electrode"),
        ({"roi": "O2", "electrode": "", "finding_type": "prior_outcome_informed_exclusion_reconfirmation"}, None),
        ({"electrode": "O2", "roi": "O2"}, None),
        ({"finding_type": "cohort_relative_summed_bca_context"}, None),
        ({"decision_scope": "recording_condition_roi"}, None),
        ({"metric": "sum_abs_roi_mean"}, None),
        ({"evidence": {"roi": "Occipital"}}, None),
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


@pytest.mark.parametrize("enabled", [False, None, "true", "false", 1])
def test_condition_interpolation_is_not_offered_without_explicit_boolean_enable(enabled):
    assert not can_interpolate_finding(_electrode_finding(), "participant", enabled)


@pytest.mark.parametrize("item, scope, expected", [
    (_electrode_finding(), "participant", True),
    (_electrode_finding(recording_id="P26-visit1"), "recording", True),
    (_electrode_finding(), "recording", False),
    (_electrode_finding(electrode="", roi="O2"), "participant", False),
    (_electrode_finding(roi="Occipital"), "participant", False),
    (_electrode_finding(condition=""), "participant", False),
    (_electrode_finding(participant_id=""), "participant", False),
])
def test_only_complete_electrode_targets_can_receive_experimental_repair(item, scope, expected):
    original = deepcopy(item)
    assert can_interpolate_finding(item, scope, True) is expected
    assert item == original


@pytest.mark.parametrize("scope", ["participant", "recording"])
def test_attention_matches_authoritative_validation_for_every_small_choice_map(scope):
    findings = [
        _electrode_finding(recording_id="P26-visit1"),
        _electrode_finding(recording_id="p26-VISIT1", participant_id="p26", electrode="o2",
                           finding_fingerprint="second-evidence"),
        _electrode_finding(recording_id="P26-visit2", condition="Other", finding_fingerprint="other-visit"),
    ]
    if scope == "participant":
        for item in findings:
            item["recording_id"] = ""
    report = {"identity_scope": scope, "condition_specific_interpolation_enabled": True,
              "review_findings": findings}
    original = deepcopy(report)
    choices = ("", *REVIEW_DECISIONS)
    for selected in product(choices, repeat=3):
        for confirmed in (False, True):
            submitted = {item["finding_fingerprint"]: {"decision": decision, "artifact_confirmed": confirmed}
                         for item, decision in zip(findings, selected)}
            before = deepcopy(submitted)
            issues = review_attention(findings, submitted, scope, True)
            try:
                validate_frequency_domain_qc_review_decisions(report, submitted)
            except ValueError:
                assert issues, (selected, confirmed)
            else:
                assert not issues, (selected, confirmed, issues)
            assert submitted == before
    assert report == original


def test_confirmation_and_conflict_remain_separate_attention_for_the_same_target():
    findings = [_electrode_finding(), _electrode_finding(finding_fingerprint="another-evidence")]
    choices = {"happy-o2": {"decision": DECISION_INTERPOLATE_CONDITION_ELECTRODE},
               "another-evidence": {"decision": DECISION_RETAIN}}
    issues = review_attention(findings, choices, "participant", True)
    assert [(issue.index, issue.kind) for issue in issues] == [
        (0, "confirmation"), (0, "conflict"), (1, "conflict"),
    ]
    assert "P26 / Neutral Happy / O2" in issues[1].message


def test_attention_conflicts_do_not_cross_recordings_or_case_distinct_conditions():
    findings = [
        _electrode_finding(recording_id="R1", condition="Faces"),
        _electrode_finding(recording_id="R1", condition="faces", finding_fingerprint="case-condition"),
        _electrode_finding(recording_id="R2", condition="Faces", finding_fingerprint="other-recording"),
    ]
    choices = {"happy-o2": {"decision": DECISION_EXCLUDE_CONDITION},
               "case-condition": {"decision": DECISION_RETAIN},
               "other-recording": {"decision": DECISION_RETAIN}}
    assert not review_attention(findings, choices, "recording", True)


def test_recording_scope_requires_canonical_recording_even_for_retain():
    findings = [_electrode_finding()]
    issues = review_attention(findings, {"happy-o2": {"decision": DECISION_RETAIN}}, "recording", False)
    assert [(issue.index, issue.kind) for issue in issues] == [(0, "invalid")]


def test_complete_choices_cannot_hide_report_level_submission_failure():
    findings = [_electrode_finding()]
    choices = {"happy-o2": {"decision": DECISION_RETAIN}}
    report = {"review_findings": findings, "screening_enabled": False}
    before = deepcopy(report)
    issues = review_attention(findings, choices, "participant", False, report=report)
    assert len(issues) == 1 and issues[0].index == -1 and issues[0].kind == "invalid"
    assert "screening is disabled" in issues[0].message
    assert report == before


def test_complete_choices_use_the_unchanged_authoritative_receipt_contract():
    findings = [_electrode_finding()]
    choices = {"happy-o2": {"decision": DECISION_RETAIN, "reason": "Original context"}}
    report = {"review_findings": findings, "identity_scope": "participant"}
    before = validate_frequency_domain_qc_review_decisions(report, choices)
    assert not review_attention(findings, choices, "participant", False, report=report)
    assert validate_frequency_domain_qc_review_decisions(report, choices) == before


@pytest.mark.parametrize("decision, required", [
    (DECISION_RETAIN, ("Independent exclusions remain active", "does not certify artifact-free")),
    (DECISION_EXCLUDE_CONDITION, ("all electrodes", "condition Neutral Happy", "recording R2", "unflagged")),
    (DECISION_EXCLUDE_RECORDING, ("every condition", "recording R2", "unflagged")),
    (DECISION_EXCLUDE_PARTICIPANT, ("every recording and condition", "participant P26", "unflagged")),
    (DECISION_INTERPOLATE_CONDITION_ELECTRODE, ("electrode O2", "recording R2", "average reference", "other channels", "review QC again")),
])
def test_consequences_name_actual_scope_and_limits_without_mutating_evidence(decision, required):
    finding = _electrode_finding(recording_id="R2")
    before = deepcopy(finding)
    text = decision_consequence(finding, decision)
    assert all(fragment in text for fragment in required)
    assert finding == before
