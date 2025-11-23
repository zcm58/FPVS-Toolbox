from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import logging
import sys
import types

import numpy as np
import pandas as pd


def _load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


tools_pkg = sys.modules.get("Tools") or types.ModuleType("Tools")
tools_pkg.__path__ = getattr(tools_pkg, "__path__", [])
stats_pkg = sys.modules.get("Tools.Stats") or types.ModuleType("Tools.Stats")
stats_pkg.__path__ = getattr(stats_pkg, "__path__", [])
legacy_pkg = sys.modules.get("Tools.Stats.Legacy") or types.ModuleType(
    "Tools.Stats.Legacy"
)
legacy_pkg.__path__ = getattr(legacy_pkg, "__path__", [])
pyside_pkg = sys.modules.get("Tools.Stats.PySide6") or types.ModuleType(
    "Tools.Stats.PySide6"
)
pyside_pkg.__path__ = getattr(pyside_pkg, "__path__", [])

sys.modules.setdefault("Tools", tools_pkg)
sys.modules.setdefault("Tools.Stats", stats_pkg)
sys.modules.setdefault("Tools.Stats.Legacy", legacy_pkg)
sys.modules.setdefault("Tools.Stats.PySide6", pyside_pkg)

stats_subjects = _load_module(
    "Tools.Stats.PySide6.stats_subjects",
    Path(__file__).parents[1] / "src/Tools/Stats/PySide6/stats_subjects.py",
)
sys.modules["Tools.Stats.PySide6.stats_subjects"] = stats_subjects
setattr(pyside_pkg, "stats_subjects", stats_subjects)

blas_limits = _load_module(
    "Tools.Stats.Legacy.blas_limits",
    Path(__file__).parents[1] / "src/Tools/Stats/Legacy/blas_limits.py",
)
sys.modules["Tools.Stats.Legacy.blas_limits"] = blas_limits
setattr(legacy_pkg, "blas_limits", blas_limits)

cross_phase_module = _load_module(
    "Tools.Stats.Legacy.cross_phase_lmm_core",
    Path(__file__).parents[1] / "src/Tools/Stats/Legacy/cross_phase_lmm_core.py",
)
sys.modules["Tools.Stats.Legacy.cross_phase_lmm_core"] = cross_phase_module
setattr(legacy_pkg, "cross_phase_lmm_core", cross_phase_module)
setattr(stats_pkg, "Legacy", legacy_pkg)
setattr(tools_pkg, "Stats", stats_pkg)

run_cross_phase_lmm = cross_phase_module.run_cross_phase_lmm
_run_backup_2x2 = cross_phase_module._run_backup_2x2


def test_cross_phase_lmm_contrasts_and_meta():
    rows = []
    subjects = {
        "S1": ("Control", {"Luteal": 1.0, "Follicular": 1.2}),
        "S2": ("Control", {"Luteal": 1.1, "Follicular": 1.3}),
        "S3": ("BC", {"Luteal": 2.0, "Follicular": 2.5}),
        "S4": ("BC", {"Luteal": 2.1, "Follicular": 2.6}),
    }
    for subject, (group, phase_values) in subjects.items():
        for phase, value in phase_values.items():
            rows.append(
                {
                    "subject": subject,
                    "group": group,
                    "phase": phase,
                    "condition": "Angry",
                    "roi": "Occipital Lobe",
                    "value": value,
                }
            )

    df_long = pd.DataFrame(rows)
    result = run_cross_phase_lmm(
        df_long, focal_condition="Angry", focal_roi="Occipital Lobe"
    )

    assert result["meta"]["n_subjects"] == len(subjects)
    assert "backup_2x2" in result
    assert "backup_2x2_used" in result["meta"]
    fixed_effects = result["fixed_effects"]
    assert fixed_effects and len(fixed_effects) > 0

    effects_of_interest = result["effects_of_interest"]
    assert effects_of_interest is not None
    contrasts = effects_of_interest.get("contrasts") or []
    groups = sorted(df_long["group"].unique().tolist())
    phases = tuple(sorted(df_long["phase"].unique().tolist()))
    expected_labels = {
        f"group_effect_phase={phases[0]}",
        f"group_effect_phase={phases[1]}",
        "group_x_phase_interaction",
    }
    assert {c.get("label") for c in contrasts} == expected_labels
    assert any(abs(c.get("estimate", 0.0)) > 1e-6 for c in contrasts)


def test_backup_2x2_produces_three_tests_and_cell_means():
    rows = []
    subjects = {
        "S1": ("Control", {"Luteal": 1.0, "Follicular": 1.1}),
        "S2": ("Control", {"Luteal": 1.2, "Follicular": 1.3}),
        "S3": ("BC", {"Luteal": 2.0, "Follicular": 2.4}),
        "S4": ("BC", {"Luteal": 2.1, "Follicular": 2.5}),
    }
    for subject, (group, phase_values) in subjects.items():
        for phase, value in phase_values.items():
            rows.append(
                {
                    "subject": subject,
                    "group": group,
                    "phase": phase,
                    "condition": "Angry",
                    "roi": "Occipital Lobe",
                    "value": value,
                }
            )

    df_long = pd.DataFrame(rows)

    logger = logging.getLogger(__name__)
    backup = _run_backup_2x2(df_long, logger)

    tests = backup.get("tests") or []
    cell_means = backup.get("cell_means") or []

    assert len(tests) == 3
    labels = {t.get("label") for t in tests}
    assert any("vs" in lbl for lbl in labels)
    assert any("difference-of-differences" in lbl for lbl in labels)

    # At least one test should have a finite t and p
    assert any(
        np.isfinite(t.get("t", float("nan"))) and np.isfinite(t.get("p", float("nan")))
        for t in tests
    )

    assert len(cell_means) > 0
