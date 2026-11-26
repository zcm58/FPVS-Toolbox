from __future__ import annotations
from datetime import datetime, timezone

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMenu, QProxyStyle, QWidget

from Main_App.settings.settings_manager import SettingsManager
from Main_App.settings.settings_paths import app_settings_file
from Main_App.gui import update_manager
from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    ACCENT_SOFT_BG,
    PAGE_BG,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    resolve_ui_color,
)
from Main_App.gui.theme import (
    appearance_is_dark,
    apply_light_palette,
    set_appearance_mode,
    set_themed_stylesheet,
    theme_color,
)


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

    assert pal.color(QPalette.Window) == QColor(PAGE_BG)
    assert pal.color(QPalette.Base) == QColor(SURFACE_BG)
    assert pal.color(QPalette.AlternateBase) == QColor(SURFACE_ALT_BG)
    assert pal.color(QPalette.Text) == QColor(TEXT_PRIMARY)
    assert pal.color(QPalette.WindowText) == QColor(TEXT_PRIMARY)
    assert pal.color(QPalette.ButtonText) == QColor(TEXT_PRIMARY)
    assert pal.color(QPalette.Highlight) == QColor(ACCENT_SOFT_BG)
    assert pal.color(QPalette.HighlightedText) == QColor(TEXT_PRIMARY)
    assert pal.color(QPalette.Link) == QColor(ACCENT_COLOR)
    assert pal.color(QPalette.Disabled, QPalette.Text) == QColor(TEXT_MUTED)
    assert pal.color(QPalette.Disabled, QPalette.ButtonText) == QColor(TEXT_MUTED)


def test_live_appearance_updates_existing_widgets_and_menus(qtbot, qapp) -> None:
    apply_light_palette(qapp)
    window = QWidget()
    qtbot.addWidget(window)
    window.setObjectName("appearanceProbe")
    local_style = f"QWidget#appearanceProbe {{ background: {SURFACE_BG}; color: {TEXT_PRIMARY}; }}"
    set_themed_stylesheet(window, local_style)
    menu = QMenu(window)
    menu.addAction("An action")
    window.show()
    qtbot.waitExposed(window)
    try:
        set_appearance_mode(qapp, "Dark")
        assert appearance_is_dark(qapp)
        assert qapp.palette().color(QPalette.Window) == theme_color(PAGE_BG)
        assert theme_color(PAGE_BG) != QColor(PAGE_BG)
        assert window.styleSheet() != local_style
        assert theme_color(SURFACE_BG).name().upper() in window.styleSheet()
        assert "chevron-down-dark.svg" in qapp.styleSheet()
        menu.ensurePolished()
        qtbot.waitUntil(lambda: menu.palette().color(QPalette.Window) == theme_color(PAGE_BG))

        fusion_style = qapp.style()
        set_appearance_mode(qapp, "Dark")
        assert qapp.style() is fusion_style

        qapp.setStyle(QProxyStyle("Fusion"))
        external_style = qapp.style()
        assert external_style is not fusion_style
        set_appearance_mode(qapp, "Dark")
        assert qapp.style() is not external_style

        set_appearance_mode(qapp, "Light")
        assert not appearance_is_dark(qapp)
        assert qapp.palette().color(QPalette.Window) == QColor(PAGE_BG)
        assert window.styleSheet() == local_style
        assert "chevron-down-dark.svg" not in qapp.styleSheet()
        qtbot.waitUntil(lambda: menu.palette().color(QPalette.Window) == QColor(PAGE_BG))

        set_appearance_mode(qapp, "Auto")
        hints = qapp.styleHints()
        assert appearance_is_dark(qapp) is (hints.colorScheme() == Qt.ColorScheme.Dark)
        for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light):
            # Exercise the same notification as a system appearance change.
            hints.setColorScheme(scheme)
            dark = hints.colorScheme() == Qt.ColorScheme.Dark
            expected = QColor(resolve_ui_color(PAGE_BG, dark=dark))
            qtbot.waitUntil(lambda: qapp.palette().color(QPalette.Window) == expected)
            assert (window.styleSheet() != local_style) is dark
            qtbot.waitUntil(lambda: menu.palette().color(QPalette.Window) == expected)
    finally:
        apply_light_palette(qapp)
