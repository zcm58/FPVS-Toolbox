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
    "Tools.LORETA_Visualizer.source_producers.project_source_psd_inputs",
    "Tools.LORETA_Visualizer.source_producers.source_model_cache",
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
'''
    result = subprocess.run(
        [sys.executable, "-c", code, module], cwd=repo_root(),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("package,module,symbol", [
    ("Tools.Stats", "Tools.Stats.ui.stats_window", "StatsWindow"),
    ("Tools.LORETA_Visualizer", "Tools.LORETA_Visualizer.gui", "LoretaVisualizerWindow"),
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
