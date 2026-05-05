from __future__ import annotations

import pytest


@pytest.mark.qt
def test_qmessagebox_static_calls_are_nonblocking():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    assert QMessageBox.critical(None, "Error", "detail") == QMessageBox.StandardButton.Ok
    assert QMessageBox.warning(None, "Warning", "detail") == QMessageBox.StandardButton.Ok
    assert QMessageBox.information(None, "Info", "detail") == QMessageBox.StandardButton.Ok
    assert QMessageBox.question(None, "Question", "detail") == QMessageBox.StandardButton.No
