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
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.theme import apply_fpvs_theme
from Main_App.gui.widgets import (
    PathPickerRow,
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
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

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        folders_card = SectionCard(
            "Folders",
            self,
            object_name="image_resizer_folders",
        )
        folders_form = make_form_layout()
        self.input_row = PathPickerRow("Browse...", folders_card)
        self.input_row.button.clicked.connect(self._select_input)
        self.in_edit = self.input_row.line_edit
        folders_form.addRow("Input Folder:", self.input_row)

        self.output_row = PathPickerRow("Browse...", folders_card)
        self.output_row.button.clicked.connect(self._select_output)
        self.out_edit = self.output_row.line_edit
        folders_form.addRow("Output Folder:", self.output_row)
        folders_card.content_layout.addLayout(folders_form)
        layout.addWidget(folders_card)

        options_card = SectionCard(
            "Resize Options",
            self,
            object_name="image_resizer_options",
        )
        options_form = make_form_layout()
        self.width_edit = QLineEdit("512")
        self.height_edit = QLineEdit("512")
        size_row = QWidget(options_card)
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(8)
        size_layout.addWidget(self.width_edit)
        size_layout.addWidget(QLabel("x", size_row))
        size_layout.addWidget(self.height_edit)
        options_form.addRow("Size:", size_row)

        self.ext_combo = QComboBox()
        self.ext_combo.addItems(["jpg", "png", "bmp"])
        options_form.addRow("Format:", self.ext_combo)

        self.overwrite_check = QCheckBox("Overwrite existing")
        options_form.addRow("", self.overwrite_check)
        options_card.content_layout.addLayout(options_form)
        layout.addWidget(options_card)

        actions_card = SectionCard("Actions", self, object_name="image_resizer_actions")
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.start_btn = make_action_button("Process", variant="primary")
        self.start_btn.clicked.connect(self._start)
        action_row.addWidget(self.start_btn)

        self.cancel_btn = make_action_button("Cancel", variant="danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(self.cancel_btn)

        self.open_btn = make_action_button("Open Folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        action_row.addWidget(self.open_btn)
        action_row.addStretch(1)
        actions_card.content_layout.addLayout(action_row)
        layout.addWidget(actions_card)

        progress_card = SectionCard("Progress", self, object_name="image_resizer_progress")
        self.status_banner = StatusBanner("Ready.", progress_card)
        progress_card.content_layout.addWidget(self.status_banner)
        self.progress = QProgressBar()
        progress_card.content_layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("logSurface", True)
        progress_card.content_layout.addWidget(self.log)
        layout.addWidget(progress_card, 1)

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
        self.status_banner.set_text("Processing images...")
        self.status_banner.set_variant("info")
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
            self.status_banner.set_text("Cancelling after the current image...")
            self.status_banner.set_variant("warning")

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
        self.status_banner.set_text(f"Finished. Processed {done} files.")
        self.status_banner.set_variant("error" if fails else "success")
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


def main() -> None:
    """Launch the Qt-based FPVS image resizer."""
    app = QApplication(sys.argv)
    apply_fpvs_theme(app)
    win = FPVSImageResizerQt()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
