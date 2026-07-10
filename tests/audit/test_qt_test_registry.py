from __future__ import annotations

from pathlib import Path

from tests.qt_test_registry import (
    find_qt_indicator_files,
    load_qt_test_registry,
    qt_tests_requested,
    requested_registered_qt_files,
    unregistered_qt_indicator_files,
)


def test_checked_in_registry_covers_all_qt_indicators() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    registry = load_qt_test_registry(repo_root)

    assert not unregistered_qt_indicator_files(repo_root, registry)


def test_indicator_scan_detects_fixture_and_application_usage(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    fixture_name = "qt" + "bot"
    application_name = "Q" + "Application"
    (tests_root / "test_widget.py").write_text(
        f"def test_widget({fixture_name}):\n    {application_name}.instance()\n",
        encoding="utf-8",
    )

    assert find_qt_indicator_files(tmp_path) == frozenset({"tests/test_widget.py"})


def test_qt_opt_in_requires_explicit_truthy_value() -> None:
    variable_name = "FPVS_ALLOW_" + "QT_TESTS"

    assert qt_tests_requested(cli_opt_in=True, environ={})
    assert qt_tests_requested(cli_opt_in=False, environ={variable_name: "yes"})
    assert not qt_tests_requested(cli_opt_in=False, environ={variable_name: "0"})


def test_explicit_registered_node_is_detected_before_collection(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_widget.py"
    test_file.parent.mkdir()
    test_file.touch()
    registry = frozenset({"tests/test_widget.py"})

    assert requested_registered_qt_files(
        [f"{test_file}::test_widget"],
        repo_root=tmp_path,
        registry=registry,
    ) == registry
