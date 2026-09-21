"""Read-only review of the comparison identities frozen before inference."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from Main_App.gui.components import AppDialog, StatusBanner, SurfaceSize, make_action_button, make_action_row


class AnalysisPlanDialog(AppDialog):
    """Show exact directions and family sizes without technical configuration."""

    def __init__(self, plan, parent=None):
        super().__init__("Review planned comparisons", parent, size=SurfaceSize(1060, 640, min_width=760, min_height=440))
        self.setObjectName("free_harmonic_analysis_plan_dialog")
        counts = {}
        for comparison in plan.comparisons:
            counts[comparison.family_id] = counts.get(comparison.family_id, 0) + 1
        note = StatusBanner(
            f"{len(plan.comparisons)} comparisons in {len(counts)} families. Holm correction uses every planned comparison in each family. "
            "Participant eligibility is checked against QC and exclusions during preparation; final counts are saved with the results.",
            self, variant="info",
        )
        note.setWordWrap(True)
        self.root_layout.addWidget(note)
        self.table = QTableWidget(len(plan.comparisons), 3, self)
        self.table.setObjectName("free_harmonic_planned_comparisons_table")
        self.table.setHorizontalHeaderLabels(("Analysis family", "Ordered comparison (A − B)", "Family tests"))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for index, comparison in enumerate(plan.comparisons):
            for column, value in enumerate((comparison.family_label, comparison.label, str(counts[comparison.family_id]))):
                item = QTableWidgetItem(value)
                item.setToolTip(comparison.label)
                self.table.setItem(index, column, item)
        self.root_layout.addWidget(self.table, 1)
        close = make_action_button("Close", variant="primary", parent=self)
        close.clicked.connect(self.accept)
        self.root_layout.addWidget(make_action_row((close,), parent=self))
