from Main_App.Shared.source_localization_optional import (
    get_source_localization_unavailable_message,
    is_source_localization_available,
)


def test_source_localization_is_quarantined_dead_code():
    assert is_source_localization_available() is False
    assert "quarantined dead code" in get_source_localization_unavailable_message()
