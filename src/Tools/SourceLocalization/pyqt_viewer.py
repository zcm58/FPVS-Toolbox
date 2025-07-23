import os
import sys
import argparse
import logging
from pathlib import Path


# ruff: noqa: E402


import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtWidgets, QtCore
import mne


SRC_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC_PATH))

from Tools.SourceLocalization.data_utils import _resolve_subjects_dir

logger = logging.getLogger(__name__)

from Main_App import SettingsManager
from Main_App import configure_logging, get_settings


class STCViewer(QtWidgets.QMainWindow):
    """Qt window for interactively viewing SourceEstimate files."""

    def __init__(self, stc_path: str, time_ms: float | None = None):
        super().__init__()
        if SettingsManager().debug_enabled():
            logger.debug(
                "Initializing STCViewer with PySide6 %s (Qt %s)",
                QtCore.__version__,
                QtCore.qVersion(),
            )
        self.setWindowTitle(os.path.basename(stc_path))
        self.stc = mne.read_source_estimate(stc_path)
        self._setup_subjects()
        self._build_ui()
        self._load_surfaces()

        start_idx = max(0, self._index_for_time(0.0))
        end_idx = min(self.stc.data.shape[1] - 1, self._index_for_time(0.5))
        self.time_slider.setRange(start_idx, end_idx)
        step = max(1, round(0.01 / self.stc.tstep))
        self.time_slider.setSingleStep(step)
        self.time_slider.setPageStep(step)

        if time_ms is not None:
            idx = self._index_for_time(time_ms / 1000)
            idx = max(start_idx, min(idx, end_idx))
        else:
            idx = start_idx
        self.time_slider.setValue(idx)
        self._update_time(idx)

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
        if SettingsManager().debug_enabled():
            logger.debug("Building UI widgets")

        self.plotter = QtInteractor(central)
        layout.addWidget(self.plotter)

        ctrl = QtWidgets.QWidget()
        ctrl_layout = QtWidgets.QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(5, 5, 5, 5)

        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._update_opacity)

        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.time_slider.setRange(0, self.stc.data.shape[1] - 1)
        self.time_slider.valueChanged.connect(self._update_time)

        self.cortex_cb = QtWidgets.QCheckBox("Show Cortex")
        show_default = SettingsManager().get('visualization', 'show_brain_mesh', 'True').lower() == 'true'
        self.cortex_cb.setChecked(show_default)
        self.cortex_cb.stateChanged.connect(self._toggle_cortex)

        ctrl_layout.addWidget(QtWidgets.QLabel("Opacity"))
        ctrl_layout.addWidget(self.opacity_slider)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(QtWidgets.QLabel("Time"))
        ctrl_layout.addWidget(self.time_slider)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(self.cortex_cb)

        layout.addWidget(ctrl)
        self.setCentralWidget(central)

    def _load_surfaces(self) -> None:
        subject = self.stc.subject or "fsaverage"
        surf_dir = self.subjects_dir / subject / "surf"
        if SettingsManager().debug_enabled():
            logger.debug("Loading surfaces for subject %s", subject)

        verts_lh, faces_lh = mne.read_surface(surf_dir / "lh.pial")
        verts_rh, faces_rh = mne.read_surface(surf_dir / "rh.pial")

        def _fmt(arr: np.ndarray) -> np.ndarray:
            return np.c_[np.full(len(arr), 3), arr].astype(np.int64)

        lh = pv.PolyData(verts_lh, _fmt(faces_lh))
        rh = pv.PolyData(verts_rh, _fmt(faces_rh))

        self.cortex_lh = self.plotter.add_mesh(
            lh, color="lightgray", opacity=0.5, name="lh"
        )
        self.cortex_rh = self.plotter.add_mesh(
            rh, color="lightgray", opacity=0.5, name="rh"
        )
        visible = self.cortex_cb.isChecked()
        self.cortex_lh.SetVisibility(visible)
        self.cortex_rh.SetVisibility(visible)

        self.heat_lh = lh.copy()
        self.heat_rh = rh.copy()
        self.heat_lh.point_data["activation"] = np.zeros(lh.n_points)
        self.heat_rh.point_data["activation"] = np.zeros(rh.n_points)
        self.act_lh = self.plotter.add_mesh(
            self.heat_lh, scalars="activation", cmap="hot", nan_opacity=0.0, name="act_lh"
        )
        self.act_rh = self.plotter.add_mesh(
            self.heat_rh, scalars="activation", cmap="hot", nan_opacity=0.0, name="act_rh"
        )
        self.plotter.add_scalar_bar(title="Source Amplitude", n_colors=8)

    def _index_for_time(self, sec: float) -> int:
        return int(round((sec - self.stc.tmin) / self.stc.tstep))

    def _update_opacity(self, value: int) -> None:
        alpha = max(0, min(100, int(value))) / 100
        for actor in (self.cortex_lh, self.cortex_rh):
            actor.GetProperty().SetOpacity(alpha)
        self.plotter.render()
        if SettingsManager().debug_enabled():
            logger.debug("Opacity set to %.2f", alpha)

    def _toggle_cortex(self, state: int) -> None:
        visible = state == QtCore.Qt.Checked
        for actor in (self.cortex_lh, self.cortex_rh):
            actor.SetVisibility(visible)
        self.plotter.render()
        if SettingsManager().debug_enabled():
            logger.debug("Cortex visibility %s", visible)

    def _update_time(self, value: int) -> None:
        idx = max(0, min(int(value), self.stc.data.shape[1] - 1))
        data = self.stc.data[:, idx]
        if SettingsManager().debug_enabled():
            logger.debug(
                "update_time idx=%s range=(%.5f, %.5f)",
                idx,
                float(data.min()),
                float(data.max()),
            )
        n_lh = len(self.stc.vertices[0])
        arr_lh = np.full(self.heat_lh.n_points, np.nan)
        arr_rh = np.full(self.heat_rh.n_points, np.nan)
        arr_lh[self.stc.vertices[0]] = data[:n_lh]
        arr_rh[self.stc.vertices[1]] = data[n_lh:]

        # Modern PyVista approach: modify mesh scalars in-place
        self.heat_lh.point_data["activation"] = arr_lh
        self.heat_rh.point_data["activation"] = arr_rh
        self.plotter.render()
        if SettingsManager().debug_enabled():
            logger.debug("Updated heatmap for time index %s", idx)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="View a source estimate file")
    parser.add_argument("--stc", required=True, help="Base STC file path")
    parser.add_argument("--time-ms", type=float, help="Initial time in ms")
    args = parser.parse_args(argv)
    configure_logging(get_settings().debug_enabled())
    os.environ.setdefault("QT_API", "pyside6")
    if SettingsManager().debug_enabled():
        logger.debug(
            "main() QT_API=%s QT_QPA_PLATFORM=%s",
            os.environ.get("QT_API"),
            os.environ.get("QT_QPA_PLATFORM"),
        )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    viewer = STCViewer(args.stc, args.time_ms)
    viewer.show()
    app.exec_()


if __name__ == "__main__":  # pragma: no cover - manual UI
    main()
