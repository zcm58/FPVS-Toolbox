from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType

from tests import repo_root

QPA_ENV_KEY = "QT_QPA_" + "PLATFORM"


def _load_configure_linux_qpa_platform():
    """Load the pure startup helper without importing Qt in this test."""
    main_path = repo_root() / "src" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_configure_linux_qpa_platform"
    )
    module = ModuleType("linux_qpa_startup")
    module.__dict__.update(
        {
            "MutableMapping": dict,
            "os": __import__("os"),
            "sys": __import__("sys"),
        }
    )
    exec(compile(ast.Module(body=[helper], type_ignores=[]), main_path, "exec"), module.__dict__)
    return module._configure_linux_qpa_platform


def test_wayland_session_with_xwayland_uses_xcb_for_vtk_compatibility() -> None:
    configure = _load_configure_linux_qpa_platform()
    environ = {
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
    }

    configure(platform_name="linux", environ=environ)

    assert environ[QPA_ENV_KEY] == "xcb"


def test_explicit_qpa_selection_is_preserved() -> None:
    configure = _load_configure_linux_qpa_platform()
    environ = {
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
        QPA_ENV_KEY: "xcb",
    }

    configure(platform_name="linux", environ=environ)

    assert environ[QPA_ENV_KEY] == "xcb"


def test_windows_and_x11_sessions_are_unchanged() -> None:
    configure = _load_configure_linux_qpa_platform()
    windows_environ = {
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":0",
    }
    x11_environ = {
        "XDG_SESSION_TYPE": "x11",
        "DISPLAY": ":0",
    }

    configure(platform_name="win32", environ=windows_environ)
    configure(platform_name="linux", environ=x11_environ)

    assert QPA_ENV_KEY not in windows_environ
    assert QPA_ENV_KEY not in x11_environ


def test_wayland_without_xwayland_display_keeps_native_default() -> None:
    configure = _load_configure_linux_qpa_platform()
    environ = {
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
    }

    configure(platform_name="linux", environ=environ)

    assert QPA_ENV_KEY not in environ


def test_qpa_configuration_precedes_pyside_import() -> None:
    main_path = Path(repo_root(), "src", "main.py")
    source = main_path.read_text(encoding="utf-8")

    assert source.index("_configure_linux_qpa_platform()") < source.index(
        "from PySide6.QtCore import QCoreApplication"
    )
