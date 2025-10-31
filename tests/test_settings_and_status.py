from __future__ import annotations
from datetime import datetime, timezone

from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from Main_App.PySide6_App.GUI import update_manager
from Main_App.PySide6_App.utils.paths import bundle_path
from Main_App.PySide6_App.utils.settings import get_app_settings


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


def test_bundle_path_qss_application(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    qtbot.addWidget(widget)
    qss_path = bundle_path("..", "..", "..", "qdark_sidebar.qss")
    original_style = app.styleSheet()
    try:
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as handle:
                app.setStyleSheet(handle.read())
        widget.show()
        qtbot.wait(10)
    finally:
        app.setStyleSheet(original_style)
