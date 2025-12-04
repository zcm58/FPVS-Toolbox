import importlib
import os

def _import_snr_utils():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "Tools",
        "Plot_Generator",
        "snr_utils.py",
    )
    spec = importlib.util.spec_from_file_location("snr_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

snr_utils = _import_snr_utils()
calc_snr_matlab = snr_utils.calc_snr_matlab


def test_calc_snr_matlab_basic():
    amps = [1, 1, 10, 1, 1, 1]
    expected = [1.0, 1.0, 10.0, 1.0, 1.0, 1.0]
    assert calc_snr_matlab(amps) == expected
