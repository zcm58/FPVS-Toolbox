import pandas as pd
import importlib.util
import sys
import types
from pathlib import Path

main_app_stub = types.ModuleType("Main_App")

class DummySettingsManager:
    def get_roi_pairs(self):
        return []


main_app_stub.SettingsManager = DummySettingsManager
sys.modules.setdefault("Main_App", main_app_stub)

spec = importlib.util.spec_from_file_location(
    "roi_resolver", Path("src/Tools/Stats/roi_resolver.py")
)
rr = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(rr)
resolve_active_rois = rr.resolve_active_rois
spec_anova = importlib.util.spec_from_file_location(
    "repeated_m_anova", Path("src/Tools/Stats/Legacy/repeated_m_anova.py")
)
anova_mod = importlib.util.module_from_spec(spec_anova)
assert spec_anova.loader is not None
sys.modules["repeated_m_anova"] = anova_mod
spec_anova.loader.exec_module(anova_mod)
run_repeated_measures_anova = anova_mod.run_repeated_measures_anova

spec_lmm = importlib.util.spec_from_file_location(
    "mixed_effects_model", Path("src/Tools/Stats/Legacy/mixed_effects_model.py")
)
lmm_mod = importlib.util.module_from_spec(spec_lmm)
assert spec_lmm.loader is not None
sys.modules["mixed_effects_model"] = lmm_mod
spec_lmm.loader.exec_module(lmm_mod)
run_mixed_effects_model = lmm_mod.run_mixed_effects_model


def test_dynamic_rois_anova_and_lmm(monkeypatch):
    def fake_get_roi_pairs(self):
        return [
            ("Left Parietal", ["P3", "P1"]),
            ("Right Parietal", ["P4", "P2"]),
            ("Left Central", ["C3", "C1"]),
            ("Right Central", ["C4", "C2"]),
        ]

    monkeypatch.setattr(rr.SettingsManager, "get_roi_pairs", fake_get_roi_pairs, raising=False)

    rois = resolve_active_rois()
    roi_names = [r.name for r in rois]
    assert roi_names[:4] == [
        "Left Parietal",
        "Right Parietal",
        "Left Central",
        "Right Central",
    ]

    subjects = ["S1", "S2"]
    conditions = ["A", "B"]
    rows = []
    for s in subjects:
        for c in conditions:
            for roi in roi_names[:4]:
                val_map = {
                    "Left Parietal": 1.0,
                    "Right Parietal": 2.0,
                    "Left Central": 3.0,
                    "Right Central": 4.0,
                }
                val = val_map[roi]
                if c == "B":
                    val += 0.5
                if s == "S2":
                    val += 0.1
                rows.append({"subject": s, "condition": c, "roi": roi, "value": val})
    df = pd.DataFrame(rows)

    anova_table = run_repeated_measures_anova(
        df, dv_col="value", within_cols=["condition", "roi"], subject_col="subject"
    )
    assert set(df["roi"].unique()) == set(roi_names[:4])
    assert not anova_table.empty

    mixed_table = run_mixed_effects_model(
        df, dv_col="value", group_col="subject", fixed_effects=["condition * roi"]
    )
    effect_text = " ".join(mixed_table["Effect"].astype(str))
    present = [name for name in roi_names[:4] if name in effect_text]
    assert len(present) >= len(roi_names[:4]) - 1
