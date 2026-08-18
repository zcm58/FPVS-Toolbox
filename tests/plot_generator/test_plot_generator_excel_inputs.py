from pathlib import Path

from Tools.Plot_Generator.excel_inputs import _infer_subject_id_from_path


def test_infer_subject_id_is_case_insensitive() -> None:
    assert _infer_subject_id_from_path(Path("p10.bdf")) == "P10"
    assert _infer_subject_id_from_path(Path("P01.bdf")) == "P01"
    assert _infer_subject_id_from_path(Path("=p17.bdf")) == "P17"


def test_infer_subject_id_prefers_known_project_participants() -> None:
    known = ["E2P2FINAL", "E2P2INITIAL"]

    assert (
        _infer_subject_id_from_path(
            Path("E2P2final_Angry_Results.xlsx"),
            known_subjects=known,
        )
        == "E2P2FINAL"
    )


def test_infer_subject_id_falls_back_to_cleaned_stem() -> None:
    assert _infer_subject_id_from_path(Path("control group.xlsx")) == "CONTROL GROUP"
    assert _infer_subject_id_from_path(Path("   .xlsx")) is None
