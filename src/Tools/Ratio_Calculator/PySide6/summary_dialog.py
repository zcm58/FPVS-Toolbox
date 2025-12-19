from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class RatioSummaryDialog(QDialog):
    def __init__(
        self,
        summary_table: list[dict[str, object]] | None,
        exclusions: list[dict[str, object]] | None,
        results_folder: Path | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ratio Summary Report")
        self._summary_table = summary_table or []
        self._exclusions = exclusions or []
        self._results_folder = Path(results_folder) if results_folder else None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("ROI summary"))

        self.summary_widget = QTableWidget(self)
        layout.addWidget(self.summary_widget)
        summary_columns = [
            "ROI",
            "Scale",
            "SigHarmonics_N",
            "N_detected",
            "N_base_valid",
            "N_outliers_excluded",
            "N_floor_excluded",
            "N_used_untrimmed",
            "Mean",
            "Median",
            "Std",
            "Variance",
            "CV%",
            "MeanRatio_fromLog",
            "MedianRatio_fromLog",
            "Min",
            "Max",
            "MinRatio",
            "MaxRatio",
            "N_used_trimmed",
            "N_trimmed_excluded",
            "Mean_trim",
            "Median_trim",
            "Std_trim",
            "Variance_trim",
            "CV%_trim",
            "MeanRatio_fromLog_trim",
            "MedianRatio_fromLog_trim",
            "Min_trim",
            "Max_trim",
            "MinRatio_trim",
            "MaxRatio_trim",
        ]
        summary_labels = self._summary_header_labels(summary_columns)
        self._populate_table(
            self.summary_widget,
            self._summary_table,
            summary_columns,
            summary_labels,
        )

        layout.addWidget(QLabel("Excluded participants"))
        self.exclusions_widget = QTableWidget(self)
        layout.addWidget(self.exclusions_widget)
        self._populate_table(self.exclusions_widget, self._exclusions, ["ROI", "PID", "Reason"])

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy", self)
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(self.copy_btn)

        self.save_btn = QPushButton("Save…", self)
        self.save_btn.clicked.connect(self._save_summary)
        btn_row.addWidget(self.save_btn)

        self.open_btn = QPushButton("Open folder", self)
        self.open_btn.clicked.connect(self._open_results_folder)
        btn_row.addWidget(self.open_btn)

        btn_row.addStretch(1)
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        self.resize(900, 600)

    def _populate_table(
        self,
        table: QTableWidget,
        data: list[dict[str, object]],
        columns: list[str],
        header_labels: list[str] | None = None,
    ) -> None:
        if not data:
            table.setRowCount(0)
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(header_labels or columns)
            return
        frame = pd.DataFrame(data)
        available_cols = [col for col in columns if col in frame.columns]
        remaining = [col for col in frame.columns if col not in available_cols]
        all_columns = available_cols + remaining
        table.setColumnCount(len(all_columns))
        if header_labels:
            labels_by_column = dict(zip(columns, header_labels))
            table.setHorizontalHeaderLabels([labels_by_column.get(col, col) for col in all_columns])
        else:
            table.setHorizontalHeaderLabels(all_columns)
        table.setRowCount(len(frame))
        for row_idx, (_, series) in enumerate(frame[all_columns].iterrows()):
            for col_idx, value in enumerate(series):
                table.setItem(row_idx, col_idx, QTableWidgetItem(self._format_value(value)))
        table.resizeColumnsToContents()

    @staticmethod
    def _format_value(value: object) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    def _summary_header_labels(self, columns: list[str]) -> list[str]:
        scale_label = self._summary_scale_label()
        if scale_label:
            suffix = "log" if scale_label == "LogRatio" else "ratio"
        else:
            suffix = ""

        def _label(col: str) -> str:
            if col in {"Mean", "Median", "Std", "Variance", "Min", "Max"} and suffix:
                return f"{col} ({suffix})"
            if col in {"Mean_trim", "Median_trim", "Std_trim", "Variance_trim", "Min_trim", "Max_trim"} and suffix:
                base = col.replace("_trim", "")
                return f"{base} ({suffix}) trim"
            return col

        return [_label(col) for col in columns]

    def _summary_scale_label(self) -> str | None:
        scales: set[str] = set()
        for entry in self._summary_table:
            scale_value = entry.get("Scale")
            if isinstance(scale_value, str):
                normalized = scale_value.replace("Scale:", "").strip()
                if normalized:
                    scales.add(normalized)
        if len(scales) == 1:
            return next(iter(scales))
        return None

    def _copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        parts: list[str] = []
        if self._summary_table:
            summary_df = pd.DataFrame(self._summary_table)
            parts.append(summary_df.to_csv(index=False))
        if self._exclusions:
            exclusions_df = pd.DataFrame(self._exclusions)
            parts.append("Exclusions\n" + exclusions_df.to_csv(index=False))
        clipboard.setText("\n".join(parts) if parts else "")

    def _save_summary(self) -> None:
        default_dir = str(self._results_folder) if self._results_folder else ""
        default_name = "ratio_summary_report.csv"
        initial_path = str(Path(default_dir) / default_name) if default_dir else default_name
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save summary",
            initial_path,
            "CSV Files (*.csv);;Text Files (*.txt)",
        )
        if not path_str:
            return
        target = Path(path_str)
        if not target.suffix:
            target = target.with_suffix(".csv")
        try:
            self._write_summary_file(target, selected_filter)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Save failed", f"Could not save summary: {exc}")

    def _write_summary_file(self, path: Path, selected_filter: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        summary_df = pd.DataFrame(self._summary_table)
        exclusion_df = pd.DataFrame(self._exclusions)
        if selected_filter.startswith("Text") or path.suffix.lower() == ".txt":
            content = ""
            if not summary_df.empty:
                content += summary_df.to_string(index=False)
            if not exclusion_df.empty:
                content += "\n\nExclusions\n" + exclusion_df.to_string(index=False)
            path.write_text(content, encoding="utf-8")
            return

        with path.open("w", encoding="utf-8") as handle:
            if not summary_df.empty:
                summary_df.to_csv(handle, index=False)
            if not exclusion_df.empty:
                handle.write("\nExclusions\n")
                exclusion_df.to_csv(handle, index=False)

    def _open_results_folder(self) -> None:
        if not self._results_folder:
            QMessageBox.information(self, "Results folder", "Results folder not available.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._results_folder)))
