from __future__ import annotations

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
