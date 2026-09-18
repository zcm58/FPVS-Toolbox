"""Compact, presentation-only decisions for one marker-timing finding."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    make_action_button,
)
from Main_App.gui.marker_occurrence_review import (
    MarkerOccurrenceReviewItem,
    marker_occurrence_review_rows,
    marker_occurrence_review_summary,
)


class MarkerOccurrenceReviewPanel(QWidget):
    """Show decision consequences while keeping exact timing evidence optional."""

    choice_requested = Signal(str)

    def __init__(
        self,
        item: MarkerOccurrenceReviewItem,
        parent: QWidget | None = None,
        *,
        index: int,
        total: int,
        group_label: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("marker_occurrence_review_panel")
        self.item = item
        self.summary = marker_occurrence_review_summary(item)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.count_label = SubsectionHeaderLabel(f"Decision {index} of {total}", self)
        self.count_label.setObjectName("marker_review_count")
        layout.addWidget(self.count_label)

        context = self.summary.context
        if group_label:
            context = f"{context} · Group: {group_label}"
        self.context_label = self._label(context, "marker_review_context")
        layout.addWidget(self.context_label)
        self.source_label = self._label(self.summary.source, "marker_review_source")
        self.source_label.setToolTip(str(item.path))
        layout.addWidget(self.source_label)

        self.finding_banner = StatusBanner(self.summary.finding, self, variant="warning")
        self.finding_banner.setObjectName("marker_review_finding")
        self.finding_banner.label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.finding_banner)
        self.required_label = self._label(
            self.summary.required_analysis, "marker_review_required_analysis",
        )
        layout.addWidget(self.required_label)

        choices_heading = SubsectionHeaderLabel("Choose what to analyze", self)
        choices_heading.setObjectName("marker_review_choices_heading")
        layout.addWidget(choices_heading)
        choices_layout = QGridLayout()
        choices_layout.setContentsMargins(0, 0, 0, 0)
        choices_layout.setHorizontalSpacing(18)
        choices_layout.setVerticalSpacing(16)
        choices_layout.setColumnStretch(1, 1)
        self.choice_buttons: dict[str, QPushButton] = {}
        self.choice_descriptions: dict[str, QLabel] = {}
        for row_index, choice in enumerate(self.summary.choices):
            button = make_action_button(choice.label, variant="secondary", parent=self)
            button.setObjectName(f"marker_review_choice_{choice.decision}")
            button.setMinimumWidth(240)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setEnabled(choice.enabled)
            button.setAccessibleDescription(choice.description)
            button.clicked.connect(
                lambda _checked=False, decision=choice.decision: self.choice_requested.emit(decision)
            )
            description = self._label(
                choice.description, f"marker_review_description_{choice.decision}",
            )
            choices_layout.addWidget(button, row_index, 0, Qt.AlignTop)
            choices_layout.addWidget(description, row_index, 1, Qt.AlignTop)
            self.choice_buttons[choice.decision] = button
            self.choice_descriptions[choice.decision] = description
        layout.addLayout(choices_layout)
        layout.addStretch(1)

        self.details_button = make_action_button("Technical details…", variant="tertiary", parent=self)
        self.details_button.setObjectName("marker_review_technical_details")
        self.details_button.clicked.connect(self._show_technical_details)
        self.cancel_button = make_action_button("Cancel Processing", parent=self)
        self.cancel_button.setObjectName("marker_review_cancel")
        self.cancel_button.clicked.connect(lambda: self.choice_requested.emit("cancel"))
        footer = ActionRow(self, alignment=Qt.AlignLeft)
        footer.setObjectName("marker_review_footer")
        footer.add_button(self.details_button)
        footer.row_layout.addStretch(1)
        footer.add_button(self.cancel_button)
        layout.addWidget(footer)

    def _label(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName(object_name)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _show_technical_details(self) -> None:
        dialog = AppDialog(
            "Marker Timing Details",
            self,
            size=SurfaceSize(width=940, height=650, min_width=620, min_height=420),
        )
        dialog.setObjectName("marker_occurrence_details_dialog")
        context = QLabel(self.context_label.text(), dialog)
        context.setTextFormat(Qt.PlainText)
        context.setWordWrap(True)
        dialog.root_layout.addWidget(context)
        viewer = QPlainTextEdit(dialog)
        viewer.setObjectName("marker_occurrence_details_viewer")
        viewer.setReadOnly(True)
        evidence = "\n\n".join(
            f"{label}\n{value}" for label, value in marker_occurrence_review_rows(self.item)
        )
        viewer.setPlainText(f"Source path\n{self.item.path}\n\n{evidence}")
        dialog.root_layout.addWidget(viewer, 1)
        close_button = make_action_button("Close", parent=dialog)
        close_button.setObjectName("marker_occurrence_details_close")
        close_button.clicked.connect(dialog.reject)
        footer = ActionRow(dialog)
        footer.add_button(close_button)
        dialog.root_layout.addWidget(footer)
        dialog.exec()
        dialog.deleteLater()
