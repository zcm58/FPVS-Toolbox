from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from config import FPVS_TOOLBOX_VERSION
from Main_App.PySide6_App.GUI import update_manager


def test_manual_force_bypasses_debounce(monkeypatch, qtbot) -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    qtbot.addWidget(parent)

    monkeypatch.setattr(update_manager, "_should_skip_update_check", lambda: True)

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {
                "tag_name": f"v{FPVS_TOOLBOX_VERSION}",
                "html_url": "https://example.test/release",
            }

    monkeypatch.setattr(update_manager.requests, "get", lambda *_args, **_kwargs: DummyResponse())

    captured: dict[str, str] = {}

    def fake_information(_parent, title: str, text: str) -> int:
        captured["title"] = title
        captured["text"] = text
        return QMessageBox.Ok

    monkeypatch.setattr(update_manager.QMessageBox, "information", fake_information)

    class DummyPool:
        def start(self, job) -> None:  # noqa: ANN001
            job.run()

    monkeypatch.setattr(QThreadPool, "globalInstance", lambda: DummyPool())

    update_manager.check_for_updates_async(
        parent,
        silent=False,
        notify_if_no_update=True,
        force=True,
    )

    qtbot.waitUntil(lambda: "title" in captured, timeout=1000)
    assert captured["title"] == "Up to Date"
    assert f"v{FPVS_TOOLBOX_VERSION}" in captured["text"]


def test_update_check_ignores_deleted_signal_source(monkeypatch) -> None:
    class BrokenSignal:
        def emit(self, *_args):
            raise RuntimeError("Signal source has been deleted")

    class BrokenResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("network unavailable")

    monkeypatch.setattr(update_manager.requests, "get", lambda *_args, **_kwargs: BrokenResponse())

    job = update_manager._CheckJob()
    job.sigs = SimpleNamespace(error=BrokenSignal())

    job.run()


def test_launch_update_check_is_skipped_under_pytest(monkeypatch, qtbot) -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    qtbot.addWidget(parent)

    started = False

    class DummyPool:
        def start(self, job) -> None:  # noqa: ANN001
            nonlocal started
            started = True

    monkeypatch.setattr(QThreadPool, "globalInstance", lambda: DummyPool())

    update_manager.check_for_updates_on_launch(parent)

    assert started is False
