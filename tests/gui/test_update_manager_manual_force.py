from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from Main_App.gui import update_manager


def test_manual_force_bypasses_debounce_and_opens_dialog(monkeypatch, qtbot) -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    qtbot.addWidget(parent)

    monkeypatch.setattr(update_manager, "_should_skip_update_check", lambda: True)
    captured: dict[str, object] = {}

    class DummyDialog:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.finished = SimpleNamespace(connect=lambda callback: captured.setdefault("finished", callback))

        def open(self) -> None:
            captured["opened"] = True

        def raise_(self) -> None:
            captured["raised"] = True

        def activateWindow(self) -> None:
            captured["activated"] = True

        def isVisible(self) -> bool:
            return True

    monkeypatch.setattr(update_manager, "UpdateDialog", DummyDialog)

    update_manager.check_for_updates_async(
        parent,
        silent=False,
        notify_if_no_update=True,
        force=True,
    )

    assert captured["opened"] is True
    assert captured["raised"] is True
    assert captured["activated"] is True
    assert captured["kwargs"]["parent"] is parent
    assert captured["kwargs"]["auto_check"] is True


def test_update_check_ignores_deleted_signal_source(monkeypatch) -> None:
    class BrokenSignal:
        def emit(self, *_args):
            raise RuntimeError("Signal source has been deleted")

    monkeypatch.setattr(
        update_manager,
        "check_for_updates",
        lambda: (_ for _ in ()).throw(RuntimeError("network unavailable")),
    )

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


def test_background_check_uses_app_owned_cancellable_lifecycle(monkeypatch, qtbot):
    from threading import Event
    from Main_App.gui.update_lifecycle import UpdateLifecycle
    from Main_App.updates.models import UpdateCheckResult
    app = QApplication.instance()
    lifecycle = UpdateLifecycle(app, quit_callback=lambda: None)
    parent = QWidget()
    qtbot.addWidget(parent)
    result = UpdateCheckResult("3.0.0", "3.0.0", False, None, "", None, False)
    seen = []
    def check(cancel):
        assert isinstance(cancel, Event)
        return result
    monkeypatch.setattr(update_manager, "update_lifecycle", lambda: lifecycle)
    monkeypatch.setattr(update_manager, "_check_for_updates_and_record", check)
    update_manager._background_check(parent, seen.append)
    qtbot.waitUntil(lambda: seen == [result])
    assert not lifecycle.has_active_jobs
    app.removeEventFilter(lifecycle)
    lifecycle.deleteLater()


def test_update_install_guard_blocks_toolbox_analysis_and_qc(monkeypatch, qtbot):
    from Main_App.gui import update_install_guard as guard
    host = QWidget()
    qtbot.addWidget(host)
    warnings = []
    monkeypatch.setattr(guard, "show_warning", lambda *args: warnings.append(args))
    host.busy = True
    assert not guard.default_install_guard(host)
    host.busy = False
    host._qc_source_prefetch_bridge = object()
    assert not guard.default_install_guard(host)
    host._qc_source_prefetch_bridge = None
    assert guard.default_install_guard(host)
    assert len(warnings) == 2
