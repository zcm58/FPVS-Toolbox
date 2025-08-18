from __future__ import annotations
import os, sys, logging
from pathlib import Path
from typing import Optional

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtWidgets, QtCore
import mne

SRC_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC_PATH))

from Tools.SourceLocalization.data_utils import _resolve_subjects_dir
from Tools.SourceLocalization.backend_utils import _ensure_pyvista_backend
from Main_App import SettingsManager, configure_logging, get_settings

logger = logging.getLogger(__name__)


class STCViewer(QtWidgets.QMainWindow):
    """Qt window for interactively viewing SourceEstimate files."""

    def __init__(self, stc_path: str, time_ms: Optional[float] = None):
        super().__init__()
        if SettingsManager().debug_enabled():
            logger.debug("STCViewer PySide6=%s Qt=%s", QtCore.__version__, QtCore.qVersion())

        self.setWindowTitle(os.path.basename(stc_path))

        # --- safe defaults (avoid race)
        self._global_vmax: float = 1.0
        self.cortex_lh = self.cortex_rh = None
        self.act_lh = self.act_rh = None
        self.heat_lh = self.heat_rh = None

        # Load STC
        self.stc = mne.read_source_estimate(stc_path)
        self._setup_subjects()
        self._build_ui()
        self._load_surfaces()

        # Global abs-max for shared clim
        try:
            self._global_vmax = float(np.abs(self.stc.data).max()) or 1.0
        except Exception:
            self._global_vmax = 1.0

        # Time slider setup (block signals while configuring)
        step = max(1, int(round(0.01 / self.stc.tstep)))  # ~10 ms step
        start_idx = max(0, self._index_for_time(0.0))
        end_idx = self.stc.data.shape[1] - 1
        if time_ms is not None:
            idx = max(start_idx, min(self._index_for_time(time_ms / 1000.0), end_idx))
        else:
            idx = start_idx

        self.time_slider.blockSignals(True)
        self.time_slider.setSingleStep(step)
        self.time_slider.setPageStep(step)
        self.time_slider.setRange(start_idx, end_idx)
        self.time_slider.setValue(idx)
        self.time_slider.blockSignals(False)
        self._update_time(idx)

    # ---- setup

    def _setup_subjects(self) -> None:
        settings = SettingsManager()
        mri_dir = settings.get("loreta", "mri_path", fallback="")
        stored = Path(mri_dir).resolve() if mri_dir else None
        subjects_dir = _resolve_subjects_dir(stored, self.stc.subject or "fsaverage")
        if not Path(subjects_dir).exists():
            subjects_dir = Path(mne.datasets.fetch_fsaverage(verbose=False)).parent
        self.subjects_dir = Path(subjects_dir)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(central)
        layout.addWidget(self.plotter)

        ctrl = QtWidgets.QWidget()
        ctrl_layout = QtWidgets.QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(8, 8, 8, 8)

        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._update_opacity)

        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_slider.valueChanged.connect(self._update_time)

        self.cortex_cb = QtWidgets.QCheckBox("Show Cortex")
        show_default = SettingsManager().get('visualization', 'show_brain_mesh', 'True').lower() == 'true'
        self.cortex_cb.setChecked(show_default)
        self.cortex_cb.stateChanged.connect(self._toggle_cortex)

        ctrl_layout.addWidget(QtWidgets.QLabel("Opacity"))
        ctrl_layout.addWidget(self.opacity_slider, 1)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(QtWidgets.QLabel("Time"))
        ctrl_layout.addWidget(self.time_slider, 3)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(self.cortex_cb)

        layout.addWidget(ctrl)
        self.setCentralWidget(central)

    def _load_surfaces(self) -> None:
        subject = self.stc.subject or "fsaverage"
        surf_dir = self.subjects_dir / subject / "surf"

        verts_lh, faces_lh = mne.read_surface(surf_dir / "lh.pial")
        verts_rh, faces_rh = mne.read_surface(surf_dir / "rh.pial")

        def _fmt(arr: np.ndarray) -> np.ndarray:
            return np.c_[np.full(len(arr), 3), arr].astype(np.int64)

        lh = pv.PolyData(verts_lh, _fmt(faces_lh))
        rh = pv.PolyData(verts_rh, _fmt(faces_rh))

        self.cortex_lh = self.plotter.add_mesh(lh, color="lightgray", opacity=0.5, name="lh")
        self.cortex_rh = self.plotter.add_mesh(rh, color="lightgray", opacity=0.5, name="rh")
        visible = self.cortex_cb.isChecked()
        self.cortex_lh.SetVisibility(visible)
        self.cortex_rh.SetVisibility(visible)

        # Heat maps
        self.heat_lh = lh.copy()
        self.heat_rh = rh.copy()
        self.heat_lh.point_data["activation"] = np.full(lh.n_points, np.nan)
        self.heat_rh.point_data["activation"] = np.full(rh.n_points, np.nan)

        clim = (0.0, self._global_vmax)

        self.act_lh = self.plotter.add_mesh(
            self.heat_lh, scalars="activation", cmap="hot", nan_opacity=0.0, name="act_lh", clim=clim
        )
        self.act_rh = self.plotter.add_mesh(
            self.heat_rh, scalars="activation", cmap="hot", nan_opacity=0.0, name="act_rh", clim=clim
        )
        self.plotter.add_scalar_bar(title="|Source| Amplitude", n_colors=8)

    # ---- interactions

    def _index_for_time(self, sec: float) -> int:
        return int(round((sec - self.stc.tmin) / self.stc.tstep))

    def _update_opacity(self, value: int) -> None:
        alpha = max(0, min(100, int(value))) / 100
        for actor in (self.cortex_lh, self.cortex_rh):
            if actor is not None:
                actor.GetProperty().SetOpacity(alpha)
        self.plotter.render()

    def _toggle_cortex(self, state: int) -> None:
        visible = state == QtCore.Qt.Checked
        for actor in (self.cortex_lh, self.cortex_rh):
            if actor is not None:
                actor.SetVisibility(visible)
        self.plotter.render()

    def _update_time(self, value: int) -> None:
        if self.stc is None or self.heat_lh is None or self.heat_rh is None:
            return
        idx = max(0, min(int(value), self.stc.data.shape[1] - 1))
        frame = np.abs(self.stc.data[:, idx])  # magnitude for sequential cmap

        n_lh = len(self.stc.vertices[0])
        arr_lh = np.full(self.heat_lh.n_points, np.nan)
        arr_rh = np.full(self.heat_rh.n_points, np.nan)
        arr_lh[self.stc.vertices[0]] = frame[:n_lh]
        arr_rh[self.stc.vertices[1]] = frame[n_lh:]

        self.heat_lh.point_data["activation"] = arr_lh
        self.heat_rh.point_data["activation"] = arr_rh

        vmax = float(getattr(self, "_global_vmax", 1.0)) or 1.0
        if self.act_lh is not None:
            self.act_lh.mapper.SetScalarRange(0.0, vmax)
        if self.act_rh is not None:
            self.act_rh.mapper.SetScalarRange(0.0, vmax)

        self.plotter.render()


def launch_viewer(stc_path: str, time_ms: Optional[float] = None) -> None:
    """Launch the STC viewer in the current PySide6 process."""
    configure_logging(get_settings().debug_enabled())
    os.environ.setdefault("QT_API", "pyside6")
    _ensure_pyvista_backend()

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    viewer = STCViewer(stc_path, time_ms)
    viewer.show()
    if not QtWidgets.QApplication.instance():
        app.exec()
