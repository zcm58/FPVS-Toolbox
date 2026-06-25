from Tools.Stats.data.stats_data_loader import scan_folder_simple


def _write_project_manifest(project_root):
    (project_root / "project.json").write_text(
        """
{
  "results_folder": ".",
  "groups": {
    "default": {
      "label": "Default",
      "folder_name": "Default"
    }
  },
  "subfolders": {
    "excel": "1 - Excel Data Files"
  }
}
""".strip(),
        encoding="utf-8",
    )


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
    (cond1 / "._P02_data.xlsx").write_text("AppleDouble metadata", encoding="utf-8")
    (cond1 / "~$P03_data.xlsx").write_text("Office lock", encoding="utf-8")

    subjects, conditions, subject_data = scan_folder_simple(str(tmp_path))

    assert subjects == ["P01"]
    assert set(conditions) == {"CondA", "CondB"}
    assert set(subject_data["P01"]) == {"CondA", "CondB"}


def test_scan_folder_reads_condition_group_layout(tmp_path):
    cond = tmp_path / "CondA"
    group = cond / "Control Group"
    group.mkdir(parents=True)
    with open(group / "P01_CondA_Results.xlsx", "w") as f:
        f.write("test")

    subjects, conditions, subject_data = scan_folder_simple(str(tmp_path))

    assert subjects == ["P01"]
    assert conditions == ["CondA"]
    assert subject_data["P01"]["CondA"].endswith("P01_CondA_Results.xlsx")


def test_scan_folder_uses_manifest_condition_when_browsing_condition_folder(tmp_path):
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    group = excel_root / "Color" / "Default"
    group.mkdir(parents=True)
    _write_project_manifest(project_root)
    workbook = group / "P01_Color_Results.xlsx"
    workbook.write_text("test", encoding="utf-8")

    subjects, conditions, subject_data = scan_folder_simple(str(excel_root / "Color"))

    assert subjects == ["P01"]
    assert conditions == ["Color"]
    assert subject_data["P01"]["Color"] == str(workbook)


def test_scan_folder_uses_manifest_condition_when_browsing_default_group_folder(tmp_path):
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    group = excel_root / "Color" / "Default"
    group.mkdir(parents=True)
    _write_project_manifest(project_root)
    workbook = group / "P01_Color_Results.xlsx"
    workbook.write_text("test", encoding="utf-8")

    subjects, conditions, subject_data = scan_folder_simple(str(group))

    assert subjects == ["P01"]
    assert conditions == ["Color"]
    assert subject_data["P01"]["Color"] == str(workbook)


def test_scan_folder_prefers_manifest_group_workbook_over_flat_legacy_copy(tmp_path):
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition = excel_root / "Color"
    group = condition / "Default"
    group.mkdir(parents=True)
    _write_project_manifest(project_root)
    flat_workbook = condition / "P01_Color_Results.xlsx"
    default_workbook = group / "P01_Color_Results.xlsx"
    flat_workbook.write_text("old", encoding="utf-8")
    default_workbook.write_text("new", encoding="utf-8")

    subjects, conditions, subject_data = scan_folder_simple(str(excel_root))

    assert subjects == ["P01"]
    assert conditions == ["Color"]
    assert subject_data["P01"]["Color"] == str(default_workbook)


def test_scan_folder_project_root_uses_manifest_excel_root_with_group_folders(tmp_path):
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    group = excel_root / "Semantic" / "Default"
    backup = project_root / "10 - Excel Data Files Backup" / "Semantic"
    group.mkdir(parents=True)
    backup.mkdir(parents=True)
    _write_project_manifest(project_root)
    workbook = group / "P01_Semantic_Results.xlsx"
    workbook.write_text("new", encoding="utf-8")
    (backup / "P01_Semantic_Results.xlsx").write_text("old", encoding="utf-8")

    subjects, conditions, subject_data = scan_folder_simple(str(project_root))

    assert subjects == ["P01"]
    assert conditions == ["Semantic"]
    assert subject_data["P01"]["Semantic"] == str(workbook)
