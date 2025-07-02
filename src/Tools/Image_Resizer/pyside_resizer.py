# pyside_resizer.py
"""PySide6 GUI for the FPVS image resizer.

This module provides a QWidget-based interface that reuses the
:func:`process_images_in_folder` logic from ``image_resize_core.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Tuple

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QWidget,
)

try:  # pragma: no cover - fallback for running as a script
    from .image_resize_core import process_images_in_folder  # type: ignore
except ImportError:
    from image_resize_core import process_images_in_folder  # type: ignore


class _Worker(QObject):
    """Worker object running image resizing in a separate thread."""

    progress = Signal(str, int, int)
    finished = Signal(list, list, int)

    def __init__(
        self,
        input_folder: str,
        output_folder: str,
        width: int,
        height: int,
        ext: str,
        overwrite: bool,
    ) -> None:
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.width = width
        self.height = height
        self.ext = ext
        self.overwrite = overwrite
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _callback(self, msg: str, processed: int, total: int) -> None:
        self.progress.emit(msg, processed, total)

    def _cancel_flag(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        skips, fails, done = process_images_in_folder(
            self.input_folder,
            self.output_folder,
            self.width,
            self.height,
            self.ext,
            update_callback=self._callback,
            cancel_flag=self._cancel_flag,
            overwrite_all=self.overwrite,
        )
        self.finished.emit(skips, fails, done)


class FPVSImageResizerQt(QWidget):
    """Qt-based widget for batch image resizing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FPVS Image Resizer")

        self.input_folder = ""
        self.output_folder = ""

        self._thread: QThread | None = None
        self._worker: _Worker | None = None

        self._apply_light_theme()
        self._build_ui()

    def _apply_light_theme(self) -> None:
        app = QApplication.instance()
        if not app:
            return
        app.setStyle("Fusion")
        palette = app.palette()
        palette.setColor(QPalette.Window, QColor("white"))
        palette.setColor(QPalette.Base, QColor("white"))
        palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.Text, QColor("black"))
        palette.setColor(QPalette.WindowText, QColor("black"))
        palette.setColor(QPalette.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ButtonText, QColor("black"))
        palette.setColor(QPalette.Highlight, QColor(76, 163, 224))
        palette.setColor(QPalette.HighlightedText, QColor("white"))
        app.setPalette(palette)

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        row = 0

        layout.addWidget(QLabel("Input Folder:"), row, 0)
        self.in_edit = QLineEdit()
        self.in_edit.setReadOnly(True)
        layout.addWidget(self.in_edit, row, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._select_input)
        layout.addWidget(btn, row, 2)
        row += 1

        layout.addWidget(QLabel("Output Folder:"), row, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        layout.addWidget(self.out_edit, row, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._select_output)
        layout.addWidget(btn, row, 2)
        row += 1

        layout.addWidget(QLabel("Width:"), row, 0)
        self.width_edit = QLineEdit("512")
        layout.addWidget(self.width_edit, row, 1)
        layout.addWidget(QLabel("Height:"), row, 2)
        self.height_edit = QLineEdit("512")
        layout.addWidget(self.height_edit, row, 3)
        row += 1

        layout.addWidget(QLabel("Format:"), row, 0)
        self.ext_combo = QComboBox()
        self.ext_combo.addItems(["jpg", "png", "bmp"])
        layout.addWidget(self.ext_combo, row, 1)

        self.overwrite_check = QCheckBox("Overwrite existing")
        layout.addWidget(self.overwrite_check, row, 2, 1, 2)
        row += 1

        self.start_btn = QPushButton("Process")
        self.start_btn.clicked.connect(self._start)
        layout.addWidget(self.start_btn, row, 0)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_btn, row, 1)

        self.open_btn = QPushButton("Open Folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        layout.addWidget(self.open_btn, row, 2)
        row += 1

        self.progress = QProgressBar()
        layout.addWidget(self.progress, row, 0, 1, 3)
        row += 1

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, row, 0, 1, 3)

    def _select_input(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.input_folder = folder
            self.in_edit.setText(folder)

    def _select_output(self) -> None:
        if not self.input_folder:
            QMessageBox.critical(self, "Error", "Select an input folder first.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            if os.path.abspath(folder) == os.path.abspath(self.input_folder):
                QMessageBox.critical(
                    self,
                    "Error",
                    "Output folder cannot be the same as the input folder.",
                )
                return
            self.output_folder = folder
            self.out_edit.setText(folder)

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text.rstrip())
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum()
        )

    def _start(self) -> None:
        try:
            width = int(self.width_edit.text())
            height = int(self.height_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Width and height must be integers.")
            return
        if not (self.input_folder and self.output_folder):
            QMessageBox.critical(self, "Error", "Select both input and output folders.")
            return
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log.clear()
        self.progress.setValue(0)

        self._thread = QThread()
        self._worker = _Worker(
            self.input_folder,
            self.output_folder,
            width,
            height,
            self.ext_combo.currentText(),
            self.overwrite_check.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, msg: str, processed: int, total: int) -> None:
        if msg:
            self._append_log(msg)
        self.progress.setValue(int(100 * processed / total) if total else 0)

    def _on_finished(
        self,
        skips: List[Tuple[str, str]],
        fails: List[Tuple[str, str]],
        done: int,
    ) -> None:
        self.cancel_btn.setEnabled(False)
        self.start_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        summary = f"Done: processed {done} files.\n"
        if skips:
            summary += (
                f"\nSkipped {len(skips)} files:\n" + "\n".join(f"  - {f}: {r}" for f, r in skips)
            )
        if fails:
            summary += (
                f"\nWrite failures {len(fails)} files:\n" + "\n".join(f"  - {f}: {e}" for f, e in fails)
            )
        QMessageBox.information(self, "Processing Summary", summary)

    def _open_folder(self) -> None:
        if not self.output_folder:
            return
        QMessageBox.information(self, "Reminder", "Please verify your images for quality.")
        if sys.platform.startswith("win"):
            os.startfile(self.output_folder)
        elif sys.platform == "darwin":
            subprocess.call(["open", self.output_folder])
        else:
            subprocess.call(["xdg-open", self.output_folder])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FPVSImageResizerQt()
    win.show()
    sys.exit(app.exec())
