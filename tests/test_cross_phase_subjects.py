from importlib.util import module_from_spec, spec_from_file_location
import sys
import types
from pathlib import Path

import pandas as pd


def _load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


stats_subjects = _load_module(
    "Tools.Stats.PySide6.stats_subjects",
    Path(__file__).parents[1] / "src/Tools/Stats/PySide6/stats_subjects.py",
)

tools_pkg = types.ModuleType("Tools")
tools_pkg.__path__ = []
stats_pkg = types.ModuleType("Tools.Stats")
stats_pkg.__path__ = []
pyside_pkg = types.ModuleType("Tools.Stats.PySide6")
pyside_pkg.__path__ = []
legacy_pkg = types.ModuleType("Tools.Stats.Legacy")
legacy_pkg.__path__ = []

sys.modules.setdefault("Tools", tools_pkg)
sys.modules.setdefault("Tools.Stats", stats_pkg)
sys.modules.setdefault("Tools.Stats.PySide6", pyside_pkg)
sys.modules.setdefault("Tools.Stats.Legacy", legacy_pkg)
sys.modules["Tools.Stats.PySide6.stats_subjects"] = stats_subjects

setattr(tools_pkg, "Stats", stats_pkg)
setattr(stats_pkg, "PySide6", pyside_pkg)
setattr(stats_pkg, "Legacy", legacy_pkg)
setattr(pyside_pkg, "stats_subjects", stats_subjects)

blas_limits = _load_module(
    "Tools.Stats.Legacy.blas_limits",
    Path(__file__).parents[1] / "src/Tools/Stats/Legacy/blas_limits.py",
)
sys.modules["Tools.Stats.Legacy.blas_limits"] = blas_limits
setattr(legacy_pkg, "blas_limits", blas_limits)

cross_phase = _load_module(
    "Tools.Stats.Legacy.cross_phase_lmm_core",
    Path(__file__).parents[1] / "src/Tools/Stats/Legacy/cross_phase_lmm_core.py",
)

build_cross_phase_long_df = cross_phase.build_cross_phase_long_df
canonical_group_and_phase_from_manifest = stats_subjects.canonical_group_and_phase_from_manifest
canonical_group_label = stats_subjects.canonical_group_label


def test_canonical_group_and_phase_from_manifest_infers_fields() -> None:
    group_name = "Luteal Control"
    entry = {"raw_input_folder": str(Path("/data/Control Group/Luteal"))}

    base_group, phase = canonical_group_and_phase_from_manifest(group_name, entry)

    assert base_group == "Control"
    assert phase == "Luteal"


def test_canonical_group_and_phase_respects_existing_fields() -> None:
    group_name = "Follicular BC"
    entry = {
        "raw_input_folder": str(Path("/data/BC Group/Follicular")),
        "base_group": "BC",
        "phase": "Follicular",
    }

    base_group, phase = canonical_group_and_phase_from_manifest(group_name, entry)

    assert base_group == "BC"
    assert phase == "Follicular"


def test_cross_phase_long_df_uses_canonical_groups() -> None:
    phase_data = {
        "Luteal": {
            "P10BCL": {"Cond": {"ROI": 1.0}},
            "P2CGL": {"Cond": {"ROI": 2.0}},
        },
        "Follicular": {
            "P10BCF": {"Cond": {"ROI": 3.0}},
            "P2CGF": {"Cond": {"ROI": 4.0}},
        },
    }

    manifest_groups = {
        "Luteal Control": {
            "raw_input_folder": str(Path("/data/Control Group/Luteal")),
            "description": "",
        },
        "Luteal BC": {
            "raw_input_folder": str(Path("/data/BC Group/Luteal")),
            "description": "",
        },
        "Follicular Control": {
            "raw_input_folder": str(Path("/data/Control Group/Follicular")),
            "description": "",
        },
        "Follicular BC": {
            "raw_input_folder": str(Path("/data/BC Group/Follicular")),
            "description": "",
        },
    }

    phase_group_maps = {
        "Luteal": {
            "P10BCL": canonical_group_label("Luteal BC", manifest_groups),
            "P2CGL": canonical_group_label("Luteal Control", manifest_groups),
        },
        "Follicular": {
            "P10BCF": canonical_group_label("Follicular BC", manifest_groups),
            "P2CGF": canonical_group_label("Follicular Control", manifest_groups),
        },
    }

    df = build_cross_phase_long_df(phase_data, phase_group_maps, ("Luteal", "Follicular"))

    assert not df.empty
    assert sorted(df["subject"].unique()) == ["P10", "P2"]
    assert set(df["group"].unique()) == {"BC", "Control"}
    assert set(df["phase"].unique()) == {"Luteal", "Follicular"}
    assert len(df) == 4
    assert isinstance(df, pd.DataFrame)

