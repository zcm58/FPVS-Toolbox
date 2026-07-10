from __future__ import annotations

import faulthandler
import hashlib
import importlib
import importlib.util
import os
import shutil
import sys
import threading
import types
import uuid
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from tests.qt_test_registry import (
    QT_TESTS_ENV_VAR,
    load_qt_test_registry,
    qt_tests_requested,
    requested_registered_qt_files,
    repo_relative_path,
    unregistered_qt_indicator_files,
)

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
_TEST_TMP_ROOT = ROOT / "test_tmp" / f"pytest-{os.getpid()}-{uuid.uuid4().hex[:10]}"

os.environ.setdefault("FPVS_TEST_MODE", "1")

_AUTO_MARK_RULES = {
    "gui": (
        "gui",
        "layout",
        "main_window",
        "settings",
        "status",
        "window",
        "dialog",
        "qt",
    ),
    "stats": (
        "anova",
        "baseline",
        "contrast",
        "harmonic",
        "lmm",
        "mixed_model",
        "multigroup",
        "outlier",
        "rm_anova",
        "stats",
    ),
    "project_io": (
        "export",
        "file_scanner",
        "manifest",
        "open_existing_project",
        "path",
        "project",
        "roundtrip",
        "scan",
    ),
    "processing": (
        "bca",
        "epoch",
        "fft",
        "pipeline",
        "post_process",
        "postprocess",
        "preproc",
        "process",
        "snr",
        "worker",
    ),
    "plot_generator": ("plot_generator",),
    "ratio": ("ratio_calculator",),
    "smoke": ("smoke",),
    "integration": ("e2e", "integration", "pipeline"),
}

_WATCHDOG_MARKERS = {"gui", "plot_generator", "qt"}
_WATCHDOG_TIMEOUT_SECONDS = int(os.environ.get("FPVS_TEST_WATCHDOG_SECONDS", "20"))
_SLOW_WATCHDOG_TIMEOUT_SECONDS = int(os.environ.get("FPVS_SLOW_TEST_WATCHDOG_SECONDS", "120"))


def pytest_addoption(parser) -> None:
    group = parser.getgroup("fpvs")
    group.addoption(
        "--allow-qt-tests",
        action="store_true",
        default=False,
        help=(
            "Collect registered Qt tests. These tests require an explicitly "
            "approved visible or CI Qt environment."
        ),
    )


def _qt_tests_allowed(config: pytest.Config) -> bool:
    return qt_tests_requested(
        cli_opt_in=bool(config.getoption("--allow-qt-tests")),
        environ=os.environ,
    )


def pytest_configure(config: pytest.Config) -> None:
    try:
        registry = load_qt_test_registry(ROOT)
    except (OSError, ValueError) as exc:
        raise pytest.UsageError(str(exc)) from exc

    missing = unregistered_qt_indicator_files(ROOT, registry)
    if missing:
        formatted = "\n".join(f"  - {path}" for path in sorted(missing))
        raise pytest.UsageError(
            "Qt-test indicators were found in files missing from "
            f"tests/qt_test_files.txt:\n{formatted}"
        )
    config._fpvs_qt_test_registry = registry
    if not _qt_tests_allowed(config):
        explicitly_requested = requested_registered_qt_files(
            config.args,
            repo_root=ROOT,
            registry=registry,
        )
        if explicitly_requested:
            formatted = "\n".join(f"  - {path}" for path in sorted(explicitly_requested))
            raise pytest.UsageError(
                "Registered Qt tests require an explicit opt-in before collection:\n"
                f"{formatted}\nSet {QT_TESTS_ENV_VAR}=1 or pass --allow-qt-tests."
            )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Keep registered Qt modules from importing without an explicit opt-in."""

    if _qt_tests_allowed(config):
        return None
    relative_path = repo_relative_path(Path(collection_path), ROOT)
    registry = config._fpvs_qt_test_registry
    if relative_path in registry:
        return True
    return None


def pytest_report_header(config: pytest.Config) -> str:
    registry = config._fpvs_qt_test_registry
    if _qt_tests_allowed(config):
        return f"FPVS Qt test guard: explicit opt-in enabled ({len(registry)} registered files)"
    return (
        f"FPVS Qt test guard: {len(registry)} registered files excluded before import; "
        f"set {QT_TESTS_ENV_VAR}=1 or pass --allow-qt-tests to opt in"
    )


def pytest_collection_modifyitems(config, items):
    registry = config._fpvs_qt_test_registry
    for item in items:
        node = f"{item.path.as_posix()}::{item.name}".lower()
        for marker_name, hints in _AUTO_MARK_RULES.items():
            if any(hint in node for hint in hints):
                item.add_marker(getattr(pytest.mark, marker_name))
        relative_path = repo_relative_path(Path(item.path), ROOT)
        if relative_path in registry:
            item.add_marker(pytest.mark.qt)


@pytest.fixture(autouse=True)
def _bounded_gui_and_plot_tests(request):
    """Fail fast on GUI/plot-generator test hangs instead of leaving pytest stuck."""

    if os.environ.get("FPVS_DISABLE_TEST_WATCHDOG") == "1":
        yield
        return
    marker_names = {marker.name for marker in request.node.iter_markers()}
    if not marker_names.intersection(_WATCHDOG_MARKERS):
        yield
        return
    timeout = (
        _SLOW_WATCHDOG_TIMEOUT_SECONDS
        if "slow" in marker_names
        else _WATCHDOG_TIMEOUT_SECONDS
    )

    def _timeout() -> None:
        sys.stderr.write(
            f"\nTest watchdog timed out after {timeout}s: {request.node.nodeid}\n"
        )
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        os._exit(124)

    timer = threading.Timer(timeout, _timeout)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def _safe_find_spec(module_name: str):
    """Return a module spec without failing on partially initialized modules."""
    try:
        return importlib.util.find_spec(module_name)
    except ValueError:
        # Some environments preload modules with __spec__ = None, which causes
        # find_spec() to raise ValueError. Clear the broken entry, then retry.
        loaded = sys.modules.get(module_name)
        if loaded is not None and getattr(loaded, "__spec__", None) is None:
            sys.modules.pop(module_name, None)
            try:
                return importlib.util.find_spec(module_name)
            except ValueError:
                return None
        return None


if _safe_find_spec("PySide6") is None:
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.__spec__ = ModuleSpec("PySide6.QtCore", loader=None)

    class _DummyQCoreApplication:
        @staticmethod
        def instance():
            return None

    class _DummyQStandardPaths:
        AppDataLocation = 0

        @staticmethod
        def writableLocation(_location):
            return "."

    class _DummyQSettings:
        def value(self, *_args, **_kwargs):
            return False

    qtcore.QCoreApplication = _DummyQCoreApplication
    qtcore.QStandardPaths = _DummyQStandardPaths
    qtcore.QSettings = _DummyQSettings

    pyside6 = types.ModuleType("PySide6")
    pyside6.__spec__ = ModuleSpec("PySide6", loader=None)
    pyside6.QtCore = qtcore

    sys.modules.setdefault("PySide6", pyside6)
    sys.modules.setdefault("PySide6.QtCore", qtcore)
else:
    pyside6 = importlib.import_module("PySide6")
    for qt_module_name in ("QtCore", "QtGui", "QtTest", "QtWidgets"):
        if _safe_find_spec(f"PySide6.{qt_module_name}") is not None:
            setattr(pyside6, qt_module_name, importlib.import_module(f"PySide6.{qt_module_name}"))

os.environ.setdefault("FPVS_CONFIG_HOME", str(_TEST_TMP_ROOT / "session_config"))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@pytest.fixture(autouse=True)
def _nonblocking_qmessagebox(monkeypatch):
    """Prevent modal QMessageBox calls from blocking automated test runs."""

    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:
        return

    ok = QMessageBox.StandardButton.Ok
    no = QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args, **_kwargs: ok, raising=False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: ok, raising=False)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: ok, raising=False)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: no, raising=False)
    monkeypatch.setattr(QMessageBox, "exec", lambda *_args, **_kwargs: ok, raising=False)
    monkeypatch.setattr(QMessageBox, "exec_", lambda *_args, **_kwargs: ok, raising=False)


def _safe_test_name(nodeid: str) -> str:
    readable = "".join(ch if ch.isalnum() else "_" for ch in nodeid)[-80:]
    digest = hashlib.sha256(nodeid.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


@pytest.fixture
def tmp_path(request):
    """
    Provide a repo-local tmp_path that avoids locked Windows pytest temp roots.

    Some Windows sandbox runs create pytest-managed temp roots with ACLs that
    are unreadable to later fixture setup. Creating the per-test directory
    directly under an ignored repo-local folder avoids that external failure.
    """

    _TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TEST_TMP_ROOT / _safe_test_name(request.node.nodeid)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=False)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_fpvs_config_home(tmp_path, monkeypatch):
    """Keep per-test GUI/settings defaults from leaking through QSettings."""

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "fpvs_config"))


def _is_windows_tmpdir_cleanup_permission_error(exc: BaseException) -> bool:
    """Return True when pytest tmpdir cleanup hits known WinError 5 ACL issues."""
    if not isinstance(exc, PermissionError):
        return False
    if getattr(exc, "winerror", None) != 5:
        return False
    tb = exc.__traceback__
    while tb is not None:
        filename = (tb.tb_frame.f_code.co_filename or "").replace("\\", "/")
        func_name = tb.tb_frame.f_code.co_name
        if filename.endswith("/_pytest/pathlib.py") and func_name == "cleanup_dead_symlinks":
            return True
        tb = tb.tb_next
    return False


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """
    Keep Windows runs actionable when pytest tmpdir ACL cleanup fails externally.

    This does not affect test execution itself; it only suppresses a known
    session-finalization crash path caused by WinError 5 in cleanup_dead_symlinks.
    """
    outcome = yield
    shutil.rmtree(_TEST_TMP_ROOT, ignore_errors=True)
    excinfo = getattr(outcome, "excinfo", None)
    if not excinfo:
        return
    exc = excinfo[1]
    if sys.platform.startswith("win") and _is_windows_tmpdir_cleanup_permission_error(exc):
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep(
                "!",
                "Ignored WinError 5 during pytest tmpdir cleanup (external ACL issue).",
            )
        outcome.force_result(None)
