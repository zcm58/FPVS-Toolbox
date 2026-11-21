"""Backend contracts must not initialize optional GUI packages."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests import repo_root


@pytest.mark.parametrize("module", [
    "Tools.Stats.analysis.dv_policy_settings",
    "Tools.Stats.analysis.canonical_harmonics",
    "Main_App.processing.harmonic_selection_qc",
    "Main_App.io.spectral_workbook",
    "Main_App.io.xlsx_xml",
    "Main_App.processing.roi_settings",
    "Main_App.processing.canonical_harmonics",
    "Tools.LORETA_Visualizer.source_producers.project_source_psd_inputs",
    "Tools.LORETA_Visualizer.source_producers.source_model_cache",
    "Tools.Sequence_Figure.renderer",
    "Main_App.projects.repeated_session_setup",
    "Tools.Individual_Detectability.export_run",
    "Main_App.processing.processing_ledger",
])
def test_backend_import_does_not_import_qt(module):
    code = '''
import importlib.abc
import sys
sys.path.insert(0, "src")
class RejectGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PySide6", "PyQt6", "tkinter"}:
            raise RuntimeError("Unexpected GUI dependency: " + fullname)
sys.meta_path.insert(0, RejectGui())
__import__(sys.argv[1])
assert "Tools.Stats.ui.stats_window" not in sys.modules
assert "Tools.LORETA_Visualizer.gui" not in sys.modules
assert "Tools.Sequence_Figure.gui" not in sys.modules
'''
    result = subprocess.run(
        [sys.executable, "-c", code, module], cwd=repo_root(),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("package,module,symbol", [
    ("Tools.Stats", "Tools.Stats.ui.stats_window", "StatsWindow"),
    ("Tools.LORETA_Visualizer", "Tools.LORETA_Visualizer.gui", "LoretaVisualizerWindow"),
    ("Tools.Sequence_Figure", "Tools.Sequence_Figure.gui", "SequenceFigureWindow"),
])
def test_public_window_export_is_lazy_and_retains_identity(package, module, symbol):
    code = '''
import importlib
import sys
from types import ModuleType
sys.path.insert(0, "src")
package_name, module_name, symbol = sys.argv[1:]
package = importlib.import_module(package_name)
assert module_name not in sys.modules
window_module = ModuleType(module_name)
window_class = type("Window", (), {})
setattr(window_module, symbol, window_class)
sys.modules[module_name] = window_module
assert getattr(package, symbol) is window_class
try:
    getattr(package, "missing_name")
except AttributeError:
    pass
else:
    raise AssertionError("Unknown public export must raise AttributeError")
'''
    result = subprocess.run(
        [sys.executable, "-c", code, package, module, symbol], cwd=repo_root(),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_shell_defers_optional_window_modules_and_keeps_public_exports():
    code = '''
import importlib
import sys
sys.path.insert(0, "src")
from Main_App.gui import main_window as shell
owners = {
    "IndividualDetectabilityWindow": ("Tools.Individual_Detectability.main_window", "IndividualDetectabilityWindow"),
    "PlotGeneratorWindow": ("Tools.Plot_Generator.plot_generator", "PlotGeneratorWindow"),
    "PublicationMapsWindow": ("Tools.Publication_Maps.gui", "PublicationMapsWindow"),
    "SensitivityAnalysisWindow": ("Tools.Sensitivity_Analysis.gui", "SensitivityAnalysisWindow"),
    "SequenceFigureWindow": ("Tools.Sequence_Figure.gui", "SequenceFigureWindow"),
    "PysideStatsWindow": ("Tools.Stats.ui.stats_window", "StatsWindow"),
}
assert owners.keys() <= set(dir(shell))
assert owners.keys() <= set(shell.__all__)
assert not any(owner in sys.modules for owner, _ in owners.values())
for name, (owner, member) in owners.items():
    window = getattr(shell, name)
    assert window is getattr(importlib.import_module(owner), member)
    assert shell._tool_window(name) is window
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=repo_root(),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
