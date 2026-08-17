from PySide6.QtWidgets import QPushButton

from Tools.Plot_Generator.gui import PlotGeneratorWindow


def test_generation_log_opens_in_focused_modal(qtbot, monkeypatch) -> None:
    window = PlotGeneratorWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    assert not hasattr(window, "console_box")
    assert not hasattr(window, "log_body")
    assert window.log is window.generation_log_dialog.viewer
    assert window.generation_log_dialog.isHidden()
    assert window.generation_log_dialog.isModal()

    window._append_log("First detail")
    window._append_log("Second detail")
    opened_with: list[str] = []
    monkeypatch.setattr(
        type(window.generation_log_dialog),
        "exec",
        lambda _dialog: opened_with.append(window.log.toPlainText()) or 0,
    )

    window.view_log_btn.click()

    assert opened_with == ["First detail\nSecond detail"]
    clear_button = window.generation_log_dialog.findChild(
        QPushButton,
        "snr_generation_log_clear",
    )
    assert clear_button is not None
    clear_button.click()
    assert window.log.toPlainText() == ""
