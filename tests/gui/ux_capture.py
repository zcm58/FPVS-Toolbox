"""Optional themed captures from explicitly approved visible Qt test runs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from Main_App.gui.theme import apply_fpvs_theme


@pytest.fixture(autouse=True)
def ux_capture_theme(qapp):
    if not os.environ.get("FPVS_UX_SCREENSHOT_DIR"):
        yield
        return
    stylesheet, palette, font = qapp.styleSheet(), qapp.palette(), qapp.font()
    style = qapp.style().objectName()
    apply_fpvs_theme(qapp)
    try:
        yield
    finally:
        qapp.setStyle(style)
        qapp.setPalette(palette)
        qapp.setFont(font)
        qapp.setStyleSheet(stylesheet)


def capture(widget, name: str) -> None:
    folder = os.environ.get("FPVS_UX_SCREENSHOT_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        QApplication.processEvents()
        assert widget.grab().save(str(path / f"{name}.png"))
