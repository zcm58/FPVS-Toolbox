import importlib.util
import sys
import types
from pathlib import Path


def _load_module(module_name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


TOOLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "Tools"
STATS_ROOT = TOOLS_ROOT / "Stats"

tools_pkg = types.ModuleType("Tools")
tools_pkg.__path__ = [str(TOOLS_ROOT)]
sys.modules.setdefault("Tools", tools_pkg)

stats_pkg = types.ModuleType("Tools.Stats")
stats_pkg.__path__ = [str(STATS_ROOT)]
sys.modules.setdefault("Tools.Stats", stats_pkg)

pyside_pkg = types.ModuleType("Tools.Stats.PySide6")
pyside_pkg.__path__ = [str(STATS_ROOT / "PySide6")]
sys.modules.setdefault("Tools.Stats.PySide6", pyside_pkg)

legacy_pkg = types.ModuleType("Tools.Stats.Legacy")
legacy_pkg.__path__ = [str(STATS_ROOT / "Legacy")]
sys.modules.setdefault("Tools.Stats.Legacy", legacy_pkg)

canonical_subjects = _load_module(
    "Tools.Stats.PySide6.stats_subjects", STATS_ROOT / "PySide6" / "stats_subjects.py"
)
cross_phase_module = _load_module(
    "Tools.Stats.Legacy.cross_phase_lmm_core", STATS_ROOT / "Legacy" / "cross_phase_lmm_core.py"
)

canonical_subject_id = canonical_subjects.canonical_subject_id
build_cross_phase_long_df = cross_phase_module.build_cross_phase_long_df


def test_canonical_subject_id_extracts_base_tag():
    assert canonical_subject_id("P10BCF") == "P10"
    assert canonical_subject_id("Sub12XYZ") == "Sub12"
    assert canonical_subject_id("S7test") == "S7"
    assert canonical_subject_id("UNKNOWN") == "UNKNOWN"


def test_build_cross_phase_long_df_uses_canonical_subjects():
    phase_data = {
        "Luteal": {
            "P10BCL": {"CondA": {"ROI1": 1.0}},
            "P2CGL": {"CondA": {"ROI1": 2.0}},
        },
        "Follicular": {
            "P10BCF": {"CondA": {"ROI1": 1.5}},
            "P2CGF": {"CondA": {"ROI1": 2.5}},
        },
    }
    phase_groups = {
        "Luteal": {"P10BCL": "BC", "P2CGL": "Control"},
        "Follicular": {"P10BCF": "BC", "P2CGF": "Control"},
    }

    df_long = build_cross_phase_long_df(phase_data, phase_groups, ("Luteal", "Follicular"))

    assert sorted(df_long["subject"].unique()) == ["P10", "P2"]
    assert set(df_long["phase"]) == {"Luteal", "Follicular"}
    assert len(df_long) == 4
