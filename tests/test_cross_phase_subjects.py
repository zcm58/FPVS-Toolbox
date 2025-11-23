import contextlib
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


def _temporary_modules(stubs: dict[str, types.ModuleType]):
    @contextlib.contextmanager
    def manager():
        existing_modules = {name: sys.modules.get(name) for name in stubs}
        sys.modules.update(stubs)
        try:
            yield
        finally:
            for name, original in existing_modules.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

    return manager()


def _preserve_modules(module_names: list[str]):
    @contextlib.contextmanager
    def manager():
        existing_modules = {name: sys.modules.get(name) for name in module_names}
        try:
            yield
        finally:
            for name, module in existing_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    return manager()


TOOLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "Tools"
STATS_ROOT = TOOLS_ROOT / "Stats"

stub_modules = {
    "Tools": types.ModuleType("Tools"),
    "Tools.Stats": types.ModuleType("Tools.Stats"),
    "Tools.Stats.PySide6": types.ModuleType("Tools.Stats.PySide6"),
    "Tools.Stats.Legacy": types.ModuleType("Tools.Stats.Legacy"),
}

stub_modules["Tools"].__path__ = [str(TOOLS_ROOT)]
stub_modules["Tools.Stats"].__path__ = [str(STATS_ROOT)]
stub_modules["Tools.Stats.PySide6"].__path__ = [str(STATS_ROOT / "PySide6")]
stub_modules["Tools.Stats.Legacy"].__path__ = [str(STATS_ROOT / "Legacy")]

with _temporary_modules(stub_modules), _preserve_modules(
    ["Tools.Stats.PySide6.stats_subjects", "Tools.Stats.Legacy.cross_phase_lmm_core"]
):
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
