import pytest

pytest.importorskip("numpy")

from Tools.Stats.PySide6.stats_controller import _unique_label


def test_unique_label_adds_suffix_when_duplicate():
    seen: set[str] = set()

    first = _unique_label("1 - Excel Data Files", seen)
    second = _unique_label("1 - Excel Data Files", seen)

    assert first == "1 - Excel Data Files"
    assert second == "1 - Excel Data Files (2)"
    assert seen == {"1 - Excel Data Files", "1 - Excel Data Files (2)"}
