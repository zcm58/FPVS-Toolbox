"""Explicit Qt-test registry parsing and completeness checks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

QT_TEST_REGISTRY_PATH = Path("tests/qt_test_files.txt")
QT_TESTS_ENV_VAR = "FPVS_ALLOW_QT_TESTS"

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_QT_TEST_INDICATORS = (
    re.compile(r"\bqtbot\b"),
    re.compile(r"\bqapp\b"),
    re.compile(r"\bQApplication\b"),
    re.compile(r"QT_QPA_PLATFORM"),
    re.compile(r"offscreen", re.IGNORECASE),
    re.compile(r"pytest\.mark\.qt\b"),
)


def qt_tests_requested(
    *,
    cli_opt_in: bool,
    environ: Mapping[str, str],
) -> bool:
    """Return whether this run explicitly opted into Qt test collection."""

    return cli_opt_in or environ.get(QT_TESTS_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def load_qt_test_registry(repo_root: Path) -> frozenset[str]:
    """Load and validate the sorted repository-relative Qt test registry."""

    registry_path = repo_root / QT_TEST_REGISTRY_PATH
    entries = [
        line.strip().replace("\\", "/")
        for line in registry_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not entries:
        raise ValueError(f"Qt test registry is empty: {registry_path}")
    if entries != sorted(set(entries)):
        raise ValueError(f"Qt test registry must contain unique, sorted paths: {registry_path}")

    for entry in entries:
        candidate = (repo_root / entry).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Qt test registry path escapes the repository: {entry}") from exc
        if not entry.startswith("tests/") or candidate.suffix != ".py":
            raise ValueError(f"Qt test registry path must name a Python test under tests/: {entry}")
        if not candidate.is_file():
            raise ValueError(f"Qt test registry path does not exist: {entry}")
    return frozenset(entries)


def repo_relative_path(path: Path, repo_root: Path) -> str | None:
    """Return a normalized repository-relative path, or ``None`` if external."""

    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def requested_registered_qt_files(
    arguments: Iterable[str],
    *,
    repo_root: Path,
    registry: frozenset[str],
) -> frozenset[str]:
    """Return registered files named explicitly in pytest path/node arguments."""

    requested: set[str] = set()
    for argument in arguments:
        path_argument = argument.split("::", maxsplit=1)[0]
        relative_path = repo_relative_path(Path(path_argument), repo_root)
        if relative_path in registry:
            requested.add(relative_path)
    return frozenset(requested)


def find_qt_indicator_files(repo_root: Path) -> frozenset[str]:
    """Find test modules containing a known QApplication/pytest-qt indicator."""

    detected: set[str] = set()
    for path in (repo_root / "tests").rglob("test_*.py"):
        source = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(source) for pattern in _QT_TEST_INDICATORS):
            detected.add(path.relative_to(repo_root).as_posix())
    return frozenset(detected)


def unregistered_qt_indicator_files(
    repo_root: Path,
    registry: frozenset[str],
) -> frozenset[str]:
    """Return indicator-bearing test files missing from the explicit registry."""

    return find_qt_indicator_files(repo_root) - registry
