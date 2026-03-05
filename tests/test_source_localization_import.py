import importlib.util
import pytest

for mod in (
    "customtkinter",
    "PySide6",
    "pyvista",
    "pyvistaqt",
    "mne",
):
    if importlib.util.find_spec(mod) is None:
        pytest.skip(f"{mod} not available", allow_module_level=True)

def test_import_source_localization():
    import quarantine.Tools.LORETA.SourceLocalization as SL
    assert hasattr(SL, "STCViewer")
