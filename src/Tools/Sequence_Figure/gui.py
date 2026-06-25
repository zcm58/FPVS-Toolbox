"""Embedded PySide6 page for FPVS sequence figure export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QFileDialog, QLineEdit, QVBoxLayout, QWidget

from Main_App.gui.components import (
    PathPickerRow,
    SectionCard,
    make_action_button,
    make_action_row,
    make_form_layout,
    show_error,
    show_info,
)
from Main_App.gui.open_paths import open_path_in_file_manager

from .renderer import DEFAULT_IMAGE_COUNT, SequenceFigureResult, SequenceFigureSpec
from .worker import SequenceFigureWorker

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
_EXPORT_BUTTON_TEXT = "Export Figure"


class SequenceFigureWindow(QWidget):
    """Embedded tool page for publication-quality FPVS sequence figures."""

    def __init__(self, parent: QWidget | None = None, project_root: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FPVS Sequence Figure")
        self._project_root = Path(project_root).resolve() if project_root else None
        self._image_paths: list[str] = [""] * DEFAULT_IMAGE_COUNT
        self._output_folder = ""
        self._thread: QThread | None = None
        self._worker: SequenceFigureWorker | None = None
        self._last_result: SequenceFigureResult | None = None
        self._build_ui()
        self._apply_project_defaults()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self._build_image_card(layout)
        self._build_labels_card(layout)
        self._build_output_card(layout)
        layout.addStretch(1)

    def _build_image_card(self, layout: QVBoxLayout) -> None:
        card = SectionCard("Stimulus Images", self, object_name="sequence_figure_images")
        form = make_form_layout()
        self.image_rows: list[PathPickerRow] = []
        for index in range(DEFAULT_IMAGE_COUNT):
            row = PathPickerRow("Browse...", card, placeholder=_image_placeholder(index))
            row.setObjectName(f"sequence_figure_image_{index + 1}_row")
            row.button.clicked.connect(lambda _checked=False, slot=index: self._select_image(slot))
            self.image_rows.append(row)
            form.addRow(f"Slot {index + 1}:", row)
        card.content_layout.addLayout(form)
        layout.addWidget(card)

    def _build_labels_card(self, layout: QVBoxLayout) -> None:
        card = SectionCard("Timing Labels", self, object_name="sequence_figure_labels")
        form = make_form_layout()
        self.base_frequency_edit = QLineEdit("6", card)
        self.oddball_frequency_edit = QLineEdit("1.2", card)
        self.basename_edit = QLineEdit("fpvs_sequence_figure", card)
        form.addRow("Presentation rate F (Hz):", self.base_frequency_edit)
        form.addRow("Oddball rate f (Hz):", self.oddball_frequency_edit)
        form.addRow("Output basename:", self.basename_edit)
        card.content_layout.addLayout(form)
        layout.addWidget(card)

    def _build_output_card(self, layout: QVBoxLayout) -> None:
        card = SectionCard("Output", self, object_name="sequence_figure_output")
        form = make_form_layout()
        self.output_row = PathPickerRow("Browse...", card, placeholder="Select output folder")
        self.output_row.setObjectName("sequence_figure_output_row")
        self.output_row.button.clicked.connect(self._select_output_folder)
        form.addRow("Output Folder:", self.output_row)
        card.content_layout.addLayout(form)

        self.export_btn = make_action_button(_EXPORT_BUTTON_TEXT, variant="primary", parent=card)
        self.export_btn.clicked.connect(self._start_export)
        self.open_btn = make_action_button("Open Output Folder", parent=card)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output_folder)
        self.action_row = make_action_row(
            [self.export_btn, self.open_btn],
            alignment=Qt.AlignLeft,
            parent=card,
        )
        card.content_layout.addWidget(self.action_row)
        layout.addWidget(card)

    def _apply_project_defaults(self) -> None:
        if self._project_root is None:
            return
        figures_dir = self._project_root / "Figures"
        if figures_dir.exists() and figures_dir.is_dir():
            self._set_output_folder(figures_dir)

    def _select_image(self, slot: int) -> None:
        start_dir = self._suggest_dialog_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _image_dialog_title(slot),
            start_dir,
            _IMAGE_FILTER,
        )
        if not file_path:
            return
        self._image_paths[slot] = file_path
        self.image_rows[slot].line_edit.setText(file_path)

    def _select_output_folder(self) -> None:
        start_dir = self._suggest_dialog_dir()
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", start_dir)
        if not folder:
            return
        self._set_output_folder(Path(folder))

    def _set_output_folder(self, folder: Path) -> None:
        self._output_folder = str(folder)
        self.output_row.line_edit.setText(self._output_folder)

    def _suggest_dialog_dir(self) -> str:
        for path_text in [self._output_folder, *self._image_paths]:
            if path_text:
                path = Path(path_text)
                folder = path if path.is_dir() else path.parent
                if folder.exists():
                    return str(folder)
        return str(self._project_root) if self._project_root is not None else ""

    def _start_export(self) -> None:
        spec = self._build_spec()
        if spec is None:
            return
        self.export_btn.setEnabled(False)
        self.export_btn.setText("Rendering...")
        self.open_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = SequenceFigureWorker(spec)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _build_spec(self) -> SequenceFigureSpec | None:
        missing = [str(index + 1) for index, path in enumerate(self._image_paths) if not path]
        if missing:
            show_error(self, "Missing Images", f"Select images for slots: {', '.join(missing)}.")
            return None
        if not self._output_folder:
            show_error(self, "Missing Output Folder", "Select an output folder.")
            return None
        return SequenceFigureSpec(
            image_paths=tuple(Path(path) for path in self._image_paths),
            output_dir=Path(self._output_folder),
            basename=self.basename_edit.text(),
            base_frequency_hz=self.base_frequency_edit.text().strip() or "6",
            oddball_frequency_hz=self.oddball_frequency_edit.text().strip() or "1.2",
        )

    def _on_progress(self, _message: str) -> None:
        return

    def _on_failed(self, message: str) -> None:
        self.export_btn.setEnabled(True)
        self.export_btn.setText(_EXPORT_BUTTON_TEXT)
        self.open_btn.setEnabled(self._last_result is not None)
        show_error(self, "Export Failed", message)
        self._worker = None

    def _on_finished(self, result: object) -> None:
        self.export_btn.setEnabled(True)
        self.export_btn.setText(_EXPORT_BUTTON_TEXT)
        self.open_btn.setEnabled(True)
        self._worker = None
        if not isinstance(result, SequenceFigureResult):
            self._on_failed("Unexpected export result.")
            return
        self._last_result = result
        show_info(self, "Export Complete", _export_message(result))

    def _on_thread_finished(self) -> None:
        self._thread = None

    def _open_output_folder(self) -> None:
        if not self._output_folder:
            return
        open_path_in_file_manager(self._output_folder)


def _image_placeholder(slot: int) -> str:
    if slot == DEFAULT_IMAGE_COUNT - 1:
        return "Select Oddball Image"
    return f"Select base image {slot + 1}"


def _image_dialog_title(slot: int) -> str:
    if slot == DEFAULT_IMAGE_COUNT - 1:
        return "Select Oddball Image"
    return f"Select Base Image {slot + 1}"


def _export_message(result: SequenceFigureResult) -> str:
    lines = ["Figure exported:", *[str(path) for path in result.output_paths]]
    if result.warnings:
        lines.extend(["", "Warnings:", *result.warnings])
    return "\n".join(lines)
