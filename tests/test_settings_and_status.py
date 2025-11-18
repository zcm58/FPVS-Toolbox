from __future__ import annotations
from datetime import datetime, timezone

from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from Main_App.PySide6_App.GUI import update_manager
from Main_App.PySide6_App.utils.settings import get_app_settings
from Main_App.PySide6_App.utils.theme import apply_light_palette


def test_get_app_settings_ini_format(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    settings = get_app_settings()
    assert settings.format() == QSettings.IniFormat
    assert app is not None
    dummy = QWidget()
    qtbot.addWidget(dummy)


def test_update_check_debounce(monkeypatch, qtbot) -> None:
    QApplication.instance() or QApplication([])
    settings = get_app_settings()
    previous = settings.value("updates/last_checked_utc", None)
    try:
        settings.setValue(
            "updates/last_checked_utc",
            datetime.now(timezone.utc).isoformat(),
        )
        settings.sync()
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
            settings.remove("updates/last_checked_utc")
        else:
            settings.setValue("updates/last_checked_utc", previous)
        settings.sync()


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
