import pytest

from Tools.LORETA_Visualizer.source_producers.inference_qualification import (
    require_confirmatory_source_inference,
    source_inference_qualification_metadata,
)


@pytest.mark.parametrize(("selection", "basis"), [
    ({"same_sample_adaptive": True, "exploratory": False}, "same_sample_adaptive"),
    ({"method_profile_id": "fixed_preregistered_domain", "exploratory": False}, "fixed_or_independent"),
    ({"exploratory": False}, "unknown"),
    ({"exploratory": True, "source": "explicit_test_injection"}, "unknown"),
    ({"method_profile_id": "dzhelyova_poncet_two_consecutive_failures"}, "same_sample_adaptive"),
    ({"calibration_status": "passed", "fwer": 0.}, "unknown"),
])
def test_no_provenance_or_synthetic_result_promotes_source_inference(selection, basis):
    result = source_inference_qualification_metadata(selection)
    assert result["source_inference_selection_basis"] == basis
    assert result["source_inference_exploratory"] is True
    assert result["source_inference_confirmatory"] is False
    assert result["source_inference_status"] == "exploratory_full_pipeline_unvalidated"


def test_confirmatory_request_requires_unavailable_qualification():
    with pytest.raises(ValueError, match="not qualified"):
        require_confirmatory_source_inference()
