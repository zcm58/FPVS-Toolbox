"""Flat, native public-dataset browser and installation feedback."""

from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar,
    QSizePolicy, QVBoxLayout, QWidget,
)

from Main_App.gui.components import (
    SubsectionHeaderLabel, apply_font_role, make_action_button, make_form_layout,
)
from Main_App.gui.style_tokens import BORDER_COLOR, PAGE_MARGIN, SURFACE_BG, TEXT_SECONDARY
from Main_App.gui.theme import set_themed_stylesheet
from Main_App.gui.typography import css_font_declaration
from Main_App.projects.experiment_library import PublicDataset


def _asset_path(filename: str) -> Path:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    return root / "assets" / "experiment_library" / filename


def _label(text: str, parent: QWidget, *, secondary: bool = False) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setProperty("librarySecondary", secondary)
    return label


class ExperimentLibraryPage(QWidget):
    """Presentation only. The workflow owns networking and project handoff."""

    primary_requested = Signal()
    cancel_requested = Signal()
    selection_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("experiment_library_page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        set_themed_stylesheet(self, f"""
            QWidget#experiment_library_page {{ background: {SURFACE_BG}; }}
            QLabel[librarySecondary="true"] {{ color: {TEXT_SECONDARY}; }}
            QLabel#libraryDatasetTitle {{ {css_font_declaration("project_title")} }}
            QFrame[libraryDivider="true"] {{ background: {BORDER_COLOR}; border: none; }}
        """)
        self._items: tuple[PublicDataset, ...] = ()
        self._busy = False
        self._progress_animation = QPropertyAnimation(self)
        self._progress_animation.setDuration(180)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(12)
        heading = _label("Experiment Library", self)
        heading.setProperty("toolTitle", True)
        apply_font_role(heading, "tool_title")
        layout.addWidget(heading)
        layout.addWidget(_label("Public datasets · No account or lab access required", self, secondary=True))
        layout.addWidget(self._divider())

        self.selector = QComboBox(self)
        self.selector.setObjectName("libraryDatasetSelector")
        self.selector.setAccessibleName("Public dataset")
        self.selector.currentIndexChanged.connect(self._select_dataset)
        self.selector.hide()
        layout.addWidget(self.selector)

        self.dataset_body = QWidget(self)
        body = QHBoxLayout(self.dataset_body)
        body.setContentsMargins(0, 6, 0, 6)
        body.setSpacing(24)
        details = QWidget(self.dataset_body)
        description = QVBoxLayout(details)
        description.setContentsMargins(0, 0, 0, 0)
        description.setSpacing(8)
        self.dataset_title = _label("", details)
        self.dataset_title.setObjectName("libraryDatasetTitle")
        apply_font_role(self.dataset_title, "project_title")
        description.addWidget(self.dataset_title)
        description.addWidget(_label("Simulated EEG", details, secondary=True))
        self.dataset_description = _label("", details)
        self.dataset_description.setObjectName("libraryDatasetDescription")
        description.addSpacing(5)
        description.addWidget(self.dataset_description)
        self.metadata = make_form_layout()
        self.participants = _label("", details)
        self.conditions = _label("", details)
        self.sample_rate = _label("", details)
        self.metadata.addRow("Participants", self.participants)
        self.metadata.addRow("Conditions", self.conditions)
        self.metadata.addRow("Sample rate", self.sample_rate)
        description.addSpacing(4)
        description.addLayout(self.metadata)
        description.addStretch(1)
        body.addWidget(details, 1)
        self.preview = QLabel(self.dataset_body)
        self.preview.setObjectName("librarySnrPreview")
        self.preview.setAccessibleName("Reference ROT SNR plot for the simulated dataset")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.preview.setMinimumSize(240, 170)
        self.preview.setMaximumSize(360, 255)
        self._preview_pixmap = QPixmap(str(_asset_path("simulated-oddball-snr.png")))
        body.addWidget(self.preview, 1)
        layout.addWidget(self.dataset_body, 1)
        self.dataset_body.hide()
        layout.addWidget(self._divider())

        action_widget = QWidget(self)
        action_widget.setMinimumHeight(90)
        action_area = QHBoxLayout(action_widget)
        action_area.setContentsMargins(0, 0, 0, 0)
        action_area.setSpacing(18)
        operation = QVBoxLayout()
        operation.setSpacing(4)
        operation.setAlignment(Qt.AlignVCenter)
        status_row = QHBoxLayout()
        self.operation_title = SubsectionHeaderLabel("Loading public datasets…", self)
        self.operation_title.setObjectName("libraryOperationTitle")
        self.operation_title.setWordWrap(True)
        self.byte_label = _label("", self, secondary=True)
        self.byte_label.setObjectName("libraryByteProgress")
        self.byte_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(self.operation_title, 1)
        status_row.addWidget(self.byte_label)
        operation.addLayout(status_row)
        self.operation_detail = _label("", self, secondary=True)
        self.operation_detail.setObjectName("libraryOperationDetail")
        operation.addWidget(self.operation_detail)
        self.progress = QProgressBar(self)
        self.progress.setObjectName("libraryDownloadProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 0)
        self._progress_animation.setTargetObject(self.progress)
        self._progress_animation.setPropertyName(b"value")
        operation.addWidget(self.progress)
        action_area.addLayout(operation, 1)
        self.primary_button = make_action_button("Try again", variant="primary", parent=self)
        self.primary_button.setObjectName("libraryDownloadAndOpen")
        self.primary_button.clicked.connect(self.primary_requested)
        self.primary_button.hide()
        self.cancel_button = make_action_button("Cancel", parent=self)
        self.cancel_button.setObjectName("libraryCancel")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()
        action_area.addWidget(self.primary_button)
        action_area.addWidget(self.cancel_button)
        layout.addWidget(action_widget)
        self.setMinimumSize(680, 390)

    def _divider(self) -> QFrame:
        divider = QFrame(self)
        divider.setProperty("libraryDivider", True)
        divider.setFixedHeight(1)
        return divider

    @property
    def selected_dataset(self) -> PublicDataset | None:
        index = self.selector.currentIndex()
        return self._items[index] if 0 <= index < len(self._items) else None

    def set_datasets(self, items: tuple[PublicDataset, ...]) -> None:
        previous = self.selected_dataset
        self._items = items
        self.selector.blockSignals(True)
        self.selector.clear()
        for item in items:
            self.selector.addItem(item.title)
        if previous in items:
            self.selector.setCurrentIndex(items.index(previous))
        self.selector.blockSignals(False)
        self.selector.setVisible(len(items) > 1)
        self.dataset_body.setVisible(bool(items))
        if items:
            self._select_dataset(self.selector.currentIndex())
        else:
            self.show_status("No public datasets available", "Try again to refresh the public catalog.")
            self.primary_button.setText("Try again")

    def _select_dataset(self, index: int) -> None:
        if not 0 <= index < len(self._items):
            return
        item = self._items[index]
        self.dataset_title.setText(item.title)
        self.dataset_description.setText(item.description)
        self.participants.setText(str(item.participant_count))
        self.conditions.setText(str(item.condition_count))
        self.sample_rate.setText(f"{item.sample_rate_hz:g} Hz")
        self.selector.setToolTip(item.title)
        self.preview.setVisible(item.item_id == "simulated-fpvs-oddball-demo")
        self._resize_preview()
        self.selection_changed.emit(item)

    def show_status(self, title: str, detail: str = "", *, busy: bool = False, cancelable: bool = False) -> None:
        self._busy = busy
        self._progress_animation.stop()
        self.operation_title.setText(title)
        self.operation_detail.setText(detail)
        self.byte_label.clear()
        self.primary_button.setVisible(not busy)
        self.cancel_button.setVisible(cancelable)
        self.cancel_button.setEnabled(cancelable)
        self.cancel_button.setText("Cancel")
        self.selector.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)

    def show_download_progress(self, received: int, total: int) -> None:
        self.byte_label.setText(f"{received / 1_000_000:.1f} of {total / 1_000_000:.1f} MB")
        percent = min(100, int(received * 100 / total)) if total else 0
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self._progress_animation.stop()
        if QApplication.isEffectEnabled(Qt.UI_AnimateCombo):
            self._progress_animation.setStartValue(self.progress.value())
            self._progress_animation.setEndValue(percent)
            self._progress_animation.start()
        else:
            self.progress.setValue(percent)

    def show_canceling(self) -> None:
        self.operation_title.setText("Canceling…")
        self.operation_detail.setText("Removing the incomplete download and project files.")
        self.cancel_button.setEnabled(False)

    def _resize_preview(self) -> None:
        if not self._preview_pixmap.isNull():
            self.preview.setPixmap(self._preview_pixmap.scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
            ))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._resize_preview()
