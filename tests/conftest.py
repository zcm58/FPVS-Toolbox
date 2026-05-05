from __future__ import annotations

import os
import sys
import types
from pathlib import Path
import importlib
import importlib.util
import shutil
from importlib.machinery import ModuleSpec

import pytest

os.environ.setdefault("FPVS_TEST_MODE", "1")


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

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
os.environ.setdefault("FPVS_CONFIG_HOME", str(ROOT / "test_tmp" / "fpvs_config"))
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
    return "".join(ch if ch.isalnum() else "_" for ch in nodeid)[-120:]


@pytest.fixture
def tmp_path(request):
    """
    Provide a repo-local tmp_path that avoids locked Windows pytest temp roots.

    Some Windows sandbox runs create pytest-managed temp roots with ACLs that
    are unreadable to later fixture setup. Creating the per-test directory
    directly under an ignored repo-local folder avoids that external failure.
    """

    base = ROOT / "test_tmp"
    base.mkdir(exist_ok=True)
    path = base / _safe_test_name(request.node.nodeid)
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
