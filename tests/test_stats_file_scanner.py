from Tools.Stats.data.stats_data_loader import scan_folder_simple


def test_scan_folder_ignores_default_dirs(tmp_path):
    cond1 = tmp_path / "CondA"
    cond1.mkdir()
    cond2 = tmp_path / "CondB"
    cond2.mkdir()
    ignore1 = tmp_path / ".FIF FILES"
    ignore1.mkdir()
    ignore2 = tmp_path / "LoReTA RESULTS"
    ignore2.mkdir()

    for folder in [cond1, cond2, ignore1, ignore2]:
        with open(folder / "P01_data.xlsx", "w") as f:
            f.write("test")

    subjects, conditions, subject_data = scan_folder_simple(str(tmp_path))

    assert subjects == ["P01"]
    assert set(conditions) == {"CondA", "CondB"}
    assert set(subject_data["P01"]) == {"CondA", "CondB"}
