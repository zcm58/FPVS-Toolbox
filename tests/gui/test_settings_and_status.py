from __future__ import annotations
from datetime import datetime, timezone

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.Shared.settings_paths import app_settings_file
from Main_App.gui import update_manager
from Main_App.gui.theme import apply_light_palette


def test_settings_manager_uses_central_ini(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    settings = SettingsManager()
    assert settings.ini_path == str(app_settings_file())
    assert app is not None
    dummy = QWidget()
    qtbot.addWidget(dummy)


def test_settings_manager_beta_tools_default_and_persistence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path))

    settings = SettingsManager()
    assert settings.beta_tools_enabled() is False

    settings.set_beta_tools_enabled(True)
    settings.save()
    assert SettingsManager().beta_tools_enabled() is True

    settings.set_beta_tools_enabled(False)
    settings.save()
    assert SettingsManager().beta_tools_enabled() is False


def test_update_check_debounce(monkeypatch, qtbot) -> None:
    QApplication.instance() or QApplication([])
    settings = SettingsManager()
    previous = settings.get("updates", "last_checked_utc", "")
    try:
        settings.set("updates", "last_checked_utc", datetime.now(timezone.utc).isoformat())
        settings.save()
        started = False

        class DummyPool:
            def start(self, job) -> None:  # noqa: ANN001
                nonlocal started
                started = True

        monkeypatch.setattr(QThreadPool, "globalInstance", lambda: DummyPool())
        update_manager.check_for_updates_async(QWidget(), silent=True)
        assert started is False
    finally:
        if previous in (None, ""):
            settings.config.remove_option("updates", "last_checked_utc")
        else:
            settings.set("updates", "last_checked_utc", previous)
        settings.save()


def test_apply_light_palette_sets_deterministic_light_theme(qtbot) -> None:
    """
    The theme helper should enforce a Fusion-based light palette regardless of OS theme.
    """
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    qtbot.addWidget(widget)

    # Apply the centralized light theme
    apply_light_palette(app)
    pal = app.palette()

    # Core surfaces: light backgrounds
    assert pal.color(QPalette.Window) == QColor("white")
    assert pal.color(QPalette.Base) == QColor("white")
    assert pal.color(QPalette.AlternateBase) == QColor(245, 245, 245)

    # Text: dark on light
    assert pal.color(QPalette.Text) == QColor("black")
    assert pal.color(QPalette.WindowText) == QColor("black")
    assert pal.color(QPalette.ButtonText) == QColor("black")

    # Highlight: fixed accent color with white highlighted text
    assert pal.color(QPalette.Highlight) == QColor(0, 120, 215)
    assert pal.color(QPalette.HighlightedText) == QColor("white")

    # Disabled text should be gray, not pure black/white
    assert pal.color(QPalette.Disabled, QPalette.Text) == QColor(128, 128, 128)
    assert pal.color(QPalette.Disabled, QPalette.ButtonText) == QColor(128, 128, 128)
