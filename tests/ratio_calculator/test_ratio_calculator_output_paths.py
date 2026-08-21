from __future__ import annotations

from pathlib import Path

from Tools.Ratio_Calculator.gui_settings import RatioSettingsMixin


def test_existing_ratio_output_directory_skips_redundant_mkdir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_mkdir(*_args, **_kwargs) -> None:
        raise AssertionError("mkdir should not run for an existing directory")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert RatioSettingsMixin._ensure_output_dir(object(), str(tmp_path)) == (
        True,
        None,
    )


def test_missing_ratio_output_directory_is_created(tmp_path: Path) -> None:
    output_dir = tmp_path / "nested" / "output"

    assert RatioSettingsMixin._ensure_output_dir(object(), str(output_dir)) == (
        True,
        None,
    )
    assert output_dir.is_dir()


def test_ratio_output_path_rejects_an_existing_file(tmp_path: Path) -> None:
    output_file = tmp_path / "output.xlsx"
    output_file.write_text("not a directory", encoding="utf-8")

    ok, error = RatioSettingsMixin._ensure_output_dir(object(), str(output_file))

    assert not ok
    assert error is not None
    assert error.startswith("Unable to create output folder:")


def test_ratio_output_directory_creation_failure_is_reported(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "blocked"

    def fail_mkdir(*_args, **_kwargs) -> None:
        raise PermissionError("read-only location")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert RatioSettingsMixin._ensure_output_dir(object(), str(output_dir)) == (
        False,
        "Unable to create output folder: read-only location",
    )
