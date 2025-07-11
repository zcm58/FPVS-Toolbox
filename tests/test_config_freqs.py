import importlib.util
import pytest

if importlib.util.find_spec("numpy") is None:
    pytest.skip("numpy not available", allow_module_level=True)
else:
    import numpy as np

from config import update_target_frequencies


def test_update_target_frequencies_full_range():
    freqs = update_target_frequencies(1.2, 16.8)
    expected = np.array([1.2 * i for i in range(1, 15)])
    assert np.allclose(freqs, expected)
