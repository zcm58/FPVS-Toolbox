"""Read-only harmonic slices of completed Free Harmonic Clustering results."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    StatusBanner,
    SubsectionHeaderLabel,
    make_action_button,
)
from Tools.Free_Harmonic_Clustering.visualization import ClusterMapData

if TYPE_CHECKING:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure


class ClusterMapView(QWidget):
    """Browse compact display snapshots without revisiting analysis inputs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("free_harmonic_cluster_map_view")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._maps: tuple[ClusterMapData, ...] = ()
        self._updating_controls = False
        self._figure: Figure | None = None
        self._canvas: FigureCanvasQTAgg | None = None
        self._build_ui()
        self._connect_signals()
        self.clear()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.run_row = QWidget(self)
        run_layout = QHBoxLayout(self.run_row)
        run_layout.setContentsMargins(0, 0, 0, 0)
        self.run_combo = self._new_combo("free_harmonic_map_run")
        run_layout.addWidget(QLabel("Comparison:", self.run_row))
        run_layout.addWidget(self.run_combo, 1)
        layout.addWidget(self.run_row)

        selectors = QHBoxLayout()
        self.cluster_combo = self._new_combo("free_harmonic_map_cluster")
        self.harmonic_combo = self._new_combo("free_harmonic_map_harmonic")
        self.previous_button = make_action_button("Previous", compact=True, parent=self)
        self.previous_button.setObjectName("free_harmonic_map_previous")
        self.previous_button.setToolTip("Show the previous available harmonic")
        self.next_button = make_action_button("Next", compact=True, parent=self)
        self.next_button.setObjectName("free_harmonic_map_next")
        self.next_button.setToolTip("Show the next available harmonic")
        selectors.addWidget(QLabel("Cluster:", self))
        selectors.addWidget(self.cluster_combo, 2)
        selectors.addWidget(QLabel("Harmonic:", self))
        selectors.addWidget(self.harmonic_combo, 1)
        selectors.addWidget(self.previous_button)
        selectors.addWidget(self.next_button)
        layout.addLayout(selectors)

        options = QHBoxLayout()
        self.members_only_checkbox = QCheckBox("Harmonics with cluster members only", self)
        self.members_only_checkbox.setObjectName("free_harmonic_map_members_only")
        self.members_only_checkbox.setToolTip(
            "Filter the view to harmonics containing members of the selected cluster(s). "
            "This does not test harmonics separately."
        )
        self.sensor_names_checkbox = QCheckBox("Show electrode names", self)
        self.sensor_names_checkbox.setObjectName("free_harmonic_map_sensor_names")
        options.addWidget(self.members_only_checkbox)
        options.addStretch(1)
        options.addWidget(self.sensor_names_checkbox)
        layout.addLayout(options)

        self.status = StatusBanner(parent=self)
        self.status.setObjectName("free_harmonic_map_status")
        layout.addWidget(self.status)

        content = QHBoxLayout()
        content.setSpacing(12)
        self.canvas_host = QWidget(self)
        self.canvas_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas_layout = QVBoxLayout(self.canvas_host)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self.canvas_host, 3)

        self.details = QWidget(self)
        self.details.setMinimumWidth(235)
        self.details.setMaximumWidth(300)
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)
        detail_layout.addWidget(SubsectionHeaderLabel("Map details", self.details))
        self.contrast_label = self._new_text_label("free_harmonic_map_contrast")
        self.legend_label = self._new_text_label("free_harmonic_map_legend")
        self.value_label = self._new_text_label("free_harmonic_map_value")
        detail_layout.addWidget(self.contrast_label)
        detail_layout.addWidget(self.legend_label)
        detail_layout.addWidget(self.value_label)
        detail_layout.addWidget(SubsectionHeaderLabel("Whole-cluster p", self.details))
        self.p_values = self._new_text_view("free_harmonic_map_cluster_p")
        self.p_values.setMaximumHeight(80)
        detail_layout.addWidget(self.p_values, 1)
        self.member_count_label = self._new_text_label("free_harmonic_map_member_count")
        detail_layout.addWidget(self.member_count_label)
        self.members = self._new_text_view("free_harmonic_map_members")
        detail_layout.addWidget(self.members, 2)
        content.addWidget(self.details, 1)
        layout.addLayout(content, 1)

        self.multiplicity = self._new_text_view("free_harmonic_map_multiplicity")
        self.multiplicity.setMaximumHeight(65)
        layout.addWidget(self.multiplicity)
        self.interpretation_label = self._new_text_label("free_harmonic_map_interpretation")
        self.interpretation_label.setText(
            "Shading is descriptive. Markers show membership in an electrode × harmonic "
            "cluster. The cluster p-value does not establish significance at an individual "
            "electrode or harmonic."
        )
        layout.addWidget(self.interpretation_label)

    def _new_combo(self, name: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(name)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
        return combo

    def _new_text_label(self, name: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _new_text_view(self, name: str) -> QPlainTextEdit:
        view = QPlainTextEdit(self)
        view.setObjectName(name)
        view.setReadOnly(True)
        view.setFrameShape(QFrame.NoFrame)
        view.setMinimumHeight(32)
        view.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        return view

    def _connect_signals(self) -> None:
        self.run_combo.currentIndexChanged.connect(self._on_run_changed)
        self.cluster_combo.currentIndexChanged.connect(self._on_cluster_changed)
        self.harmonic_combo.currentIndexChanged.connect(self._refresh_view)
        self.members_only_checkbox.toggled.connect(self._on_cluster_changed)
        self.sensor_names_checkbox.toggled.connect(self._refresh_view)
        self.previous_button.clicked.connect(lambda: self._step_harmonic(-1))
        self.next_button.clicked.connect(lambda: self._step_harmonic(1))

    def set_maps(self, maps: tuple[ClusterMapData, ...]) -> None:
        """Replace current-session display data and reset all view selections."""

        snapshots = tuple(maps)
        if any(not isinstance(data, ClusterMapData) for data in snapshots):
            raise TypeError("Cluster maps must be ClusterMapData snapshots.")
        self.clear()
        self._maps = snapshots
        self._updating_controls = True
        try:
            for index, data in enumerate(snapshots):
                label = data.run_label or f"{data.arm_a_label} − {data.arm_b_label}"
                self.run_combo.addItem(label, index)
        finally:
            self._updating_controls = False
        self.run_row.setVisible(len(snapshots) > 1)
        self.run_combo.setEnabled(bool(snapshots))
        self.members_only_checkbox.setEnabled(bool(snapshots))
        self.sensor_names_checkbox.setEnabled(bool(snapshots))
        self._on_run_changed()

    def clear(self) -> None:
        """Discard all result snapshots, selections, and any rendered map."""

        self._maps = ()
        self._updating_controls = True
        try:
            for combo in (self.run_combo, self.cluster_combo, self.harmonic_combo):
                combo.clear()
                combo.setEnabled(False)
            self.members_only_checkbox.setChecked(True)
            self.sensor_names_checkbox.setChecked(False)
        finally:
            self._updating_controls = False
        self.run_row.hide()
        self.members_only_checkbox.setEnabled(False)
        self.sensor_names_checkbox.setEnabled(False)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.status.set_variant("info")
        self.status.set_text("Run an analysis to view cluster maps.")
        self.details.hide()
        self.multiplicity.clear()
        self.multiplicity.hide()
        for label in (self.contrast_label, self.legend_label, self.value_label, self.member_count_label):
            label.clear()
        self.p_values.clear()
        self.members.clear()
        if self._figure is not None:
            self._figure.clear()
        if self._canvas is not None:
            self._canvas.draw_idle()
            self._canvas.hide()

    def select_run(self, run_index: int) -> bool:
        """Select an existing run; invalid row selections leave the view intact."""

        if not 0 <= run_index < len(self._maps):
            return False
        self.run_combo.setCurrentIndex(run_index)
        return True

    def select_cluster(self, cluster_id: int, run_index: int = 0) -> bool:
        """Navigate from an analysis row using its original signed cluster ID."""

        if not 0 <= run_index < len(self._maps):
            return False
        if cluster_id not in {cluster.cluster_id for cluster in self._maps[run_index].clusters}:
            return False
        self.select_run(run_index)
        self.cluster_combo.setCurrentIndex(self.cluster_combo.findData(cluster_id))
        return True

    def _current_data(self) -> ClusterMapData | None:
        index = self.run_combo.currentIndex()
        return self._maps[index] if 0 <= index < len(self._maps) else None

    def _selected_cluster_id(self) -> int | None:
        value = self.cluster_combo.currentData()
        return None if value is None else int(value)

    def _on_run_changed(self, *_args: object) -> None:
        if self._updating_controls:
            return
        data = self._current_data()
        self._updating_controls = True
        try:
            self.cluster_combo.clear()
            if data is not None:
                self.cluster_combo.addItem("All significant clusters", None)
                for cluster in data.clusters:
                    self.cluster_combo.addItem(f"Cluster {cluster.cluster_id:+d}", cluster.cluster_id)
            self.cluster_combo.setEnabled(data is not None and bool(data.clusters))
        finally:
            self._updating_controls = False
        self._populate_harmonics(preserve_selection=False)

    def _on_cluster_changed(self, *_args: object) -> None:
        if not self._updating_controls:
            self._populate_harmonics(preserve_selection=True)

    def _membership_mask(self, data: ClusterMapData) -> np.ndarray:
        cluster_id = self._selected_cluster_id()
        return data.cluster_labels != 0 if cluster_id is None else data.cluster_labels == cluster_id

    def _populate_harmonics(self, *, preserve_selection: bool) -> None:
        data = self._current_data()
        previous = self.harmonic_combo.currentData() if preserve_selection else None
        self._updating_controls = True
        try:
            self.harmonic_combo.clear()
            if data is not None:
                eligible = (
                    np.any(self._membership_mask(data), axis=0)
                    if self.members_only_checkbox.isChecked()
                    else np.ones(len(data.harmonic_orders), dtype=bool)
                )
                for harmonic_index in np.flatnonzero(eligible):
                    index = int(harmonic_index)
                    label = f"H{data.harmonic_orders[index]} ({data.harmonics_hz[index]:g} Hz)"
                    self.harmonic_combo.addItem(label, index)
                previous_index = self.harmonic_combo.findData(previous) if previous is not None else -1
                if previous_index >= 0:
                    self.harmonic_combo.setCurrentIndex(previous_index)
            self.harmonic_combo.setEnabled(self.harmonic_combo.count() > 0)
        finally:
            self._updating_controls = False
        self._refresh_view()

    def _step_harmonic(self, step: int) -> None:
        target = self.harmonic_combo.currentIndex() + step
        if 0 <= target < self.harmonic_combo.count():
            self.harmonic_combo.setCurrentIndex(target)

    def _refresh_view(self, *_args: object) -> None:
        if self._updating_controls:
            return
        data = self._current_data()
        if data is None:
            return
        current = self.harmonic_combo.currentIndex()
        self.previous_button.setEnabled(current > 0)
        self.next_button.setEnabled(0 <= current < self.harmonic_combo.count() - 1)
        harmonic = self.harmonic_combo.currentData()
        index = None if harmonic is None else int(harmonic)
        self._populate_details(data, index)
        self._draw_map(data, index)

    def _populate_details(self, data: ClusterMapData, harmonic_index: int | None) -> None:
        self.details.show()
        self.contrast_label.setText(f"Contrast: {data.arm_a_label} − {data.arm_b_label}")
        self.legend_label.setText(
            f"Black markers: {data.arm_a_label} > {data.arm_b_label}\n"
            f"White markers: {data.arm_b_label} > {data.arm_a_label}"
        )
        self.value_label.setText(f"Shading: {data.value_label}")
        self.multiplicity.setPlainText(data.multiplicity_note)
        self.multiplicity.setVisible(bool(data.multiplicity_note))
        cluster_id = self._selected_cluster_id()
        clusters = tuple(
            cluster for cluster in data.clusters if cluster_id is None or cluster.cluster_id == cluster_id
        )
        self.p_values.setPlainText(
            "\n".join(f"Cluster {cluster.cluster_id:+d}: raw p = {cluster.p_value:.4g}" for cluster in clusters)
            or "No significant clusters."
        )
        if harmonic_index is None:
            self.member_count_label.setText("No harmonic slice selected")
            self.members.setPlainText("No cluster members are available in this view.")
            self.status.set_variant("info")
            self.status.set_text(
                "No significant clusters. Uncheck ‘Harmonics with cluster members only’ "
                "to view all analyzed harmonics descriptively."
                if not data.clusters
                else "No harmonics contain members of the selected cluster."
            )
            return

        mask = self._membership_mask(data)[:, harmonic_index]
        member_count = int(np.count_nonzero(mask))
        order = data.harmonic_orders[harmonic_index]
        self.member_count_label.setText(f"H{order}: {member_count} member electrodes")
        member_lines = []
        for cluster in clusters:
            names = tuple(
                name
                for sensor, name in enumerate(data.sensor_names)
                if int(data.cluster_labels[sensor, harmonic_index]) == cluster.cluster_id
            )
            if names:
                member_lines.append(f"Cluster {cluster.cluster_id:+d} ({len(names)} electrodes):\n{', '.join(names)}")
        self.members.setPlainText(
            "\n\n".join(member_lines) or "No selected-cluster members at this harmonic."
        )
        self.status.set_variant("info")
        if not data.clusters:
            text = "No significant clusters. Showing a descriptive difference map only."
        elif not member_count:
            text = "This harmonic has no members of the selected cluster(s). Shading remains descriptive."
        else:
            label = "significant clusters" if cluster_id is None else f"Cluster {cluster_id:+d}"
            text = f"H{order} slice of {label}. Whole-cluster p-values apply across the cluster's harmonics."
        self.status.set_text(text)

    def _ensure_canvas(self) -> None:
        if self._canvas is not None:
            return
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self._figure = Figure(figsize=(5.2, 4.0), dpi=100, facecolor="white")
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setObjectName("free_harmonic_map_canvas")
        self._canvas.setMinimumSize(0, 0)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas_layout.addWidget(self._canvas)

    def _draw_map(self, data: ClusterMapData, harmonic_index: int | None) -> None:
        self._ensure_canvas()
        assert self._figure is not None and self._canvas is not None
        self._figure.clear()
        self._canvas.show()
        if harmonic_index is None:
            self._canvas.draw_idle()
            return
        from Tools.Free_Harmonic_Clustering.render_cluster_maps import draw_harmonic_map

        axis = self._figure.add_subplot(111)
        mappable = draw_harmonic_map(
            axis,
            data,
            harmonic_index,
            cluster_id=self._selected_cluster_id(),
            show_sensor_names=self.sensor_names_checkbox.isChecked(),
        )
        colorbar = self._figure.colorbar(mappable, ax=axis, fraction=0.035, pad=0.04, shrink=0.8)
        colorbar.ax.tick_params(labelsize=8)
        colorbar.set_label("Mean difference", fontsize=9)
        if not np.any(data.mean_difference):
            colorbar.set_ticks([0.0])
        self._figure.subplots_adjust(left=0.03, right=0.88, bottom=0.06, top=0.92)
        self._canvas.draw_idle()


__all__ = ["ClusterMapView"]
