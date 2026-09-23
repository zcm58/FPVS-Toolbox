"""Compact controls for the optional third through fifth SNR conditions."""

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from Main_App.gui.components import SubsectionHeaderLabel


EXTRA_CONDITION_COLORS = ("#009E73", "#CC79A7", "#D5A000")


def configure_condition_combo(combo) -> None:
    combo.setMinimumContentsLength(12)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.currentTextChanged.connect(combo.setToolTip)


def build_extra_condition_selectors(owner, grid) -> None:
    owner.extra_condition_combos = []
    owner.extra_condition_containers = []
    owner.extra_color_buttons = []
    for index, letter in enumerate("CDE"):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(SubsectionHeaderLabel(f"Condition {letter}"))
        row = QHBoxLayout()
        row.setSpacing(6)
        combo = QComboBox()
        configure_condition_combo(combo)
        combo.setObjectName(f"snr_condition_{letter.lower()}")
        combo.setAccessibleName(f"Condition {letter} to compare")
        combo.setPlaceholderText("Choose condition")
        combo.currentTextChanged.connect(owner._on_condition_b_changed)
        button = QPushButton()
        button.setFixedSize(20, 20)
        button.setAccessibleName(f"Choose Condition {letter} line color")
        button.setToolTip(f"Color for Condition {letter}")
        button.setStyleSheet(f"background-color: {owner.extra_colors[index]};")
        button.clicked.connect(lambda _checked=False, key=letter.lower(): owner._choose_color(key))
        row.addWidget(combo, 1)
        row.addWidget(button)
        layout.addLayout(row)
        grid.addWidget(container, (index + 3) // 2, (index + 3) % 2)
        owner.extra_condition_combos.append(combo)
        owner.extra_condition_containers.append(container)
        owner.extra_color_buttons.append(button)


def build_overlay_count(owner, layout) -> None:
    owner.overlay_count_label = QLabel("Conditions:")
    owner.overlay_count_spin = QSpinBox()
    owner.overlay_count_spin.setObjectName("snr_overlay_condition_count")
    owner.overlay_count_spin.setAccessibleName("Number of conditions to overlay")
    owner.overlay_count_spin.setRange(2, 5)
    owner.overlay_count_spin.setValue(2)
    owner.overlay_count_spin.setToolTip("Compare two to five different conditions on one SNR plot.")
    owner.overlay_count_spin.valueChanged.connect(owner._on_overlay_count_changed)
    owner.overlay_count_label.setBuddy(owner.overlay_count_spin)
    layout.addWidget(owner.overlay_count_label)
    layout.addWidget(owner.overlay_count_spin)


def build_extra_legend_fields(owner, grid) -> None:
    owner.extra_legend_widgets = []
    for index, letter in enumerate("cde"):
        widgets = []
        for column, key, caption in (
            (0, f"condition_{letter}_label", f"Condition {letter.upper()} label:"),
            (2, f"{letter}_peaks_label", f"{letter.upper()}-Peaks label:"),
        ):
            label = QLabel(caption)
            label.setFixedWidth(owner.legend_condition_a_label.width())
            edit = QLineEdit()
            edit.setMinimumWidth(0)
            edit.setPlaceholderText(caption.rstrip(":"))
            edit.setAccessibleName(caption.rstrip(":"))
            edit.textChanged.connect(owner._persist_legend_settings)
            if column == 0:
                edit.textEdited.connect(lambda _text, field=key: owner._on_legend_condition_label_edited(field))
            else:
                edit.textEdited.connect(lambda _text, field=key: owner._mark_legend_manual_override(field))
            grid.addWidget(label, index + 2, column)
            grid.addWidget(edit, index + 2, column + 1)
            owner._legend_fields[key] = edit
            widgets.extend((label, edit))
        owner.extra_legend_widgets.append(widgets)
