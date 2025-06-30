import os
import sys
import argparse
from pathlib import Path


# ruff: noqa: E402


import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PyQt5 import QtWidgets, QtCore
import mne


SRC_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC_PATH))

from Tools.SourceLocalization.data_utils import _resolve_subjects_dir

from Main_App.settings_manager import SettingsManager


class STCViewer(QtWidgets.QMainWindow):
    """Qt window for interactively viewing SourceEstimate files."""

    def __init__(self, stc_path: str, time_ms: float | None = None):
        super().__init__()
        self.setWindowTitle(os.path.basename(stc_path))
        self.stc = mne.read_source_estimate(stc_path)
        self._setup_subjects()
        self._build_ui()
        self._load_surfaces()
        if time_ms is not None:
            idx = int(round((time_ms / 1000 - self.stc.tmin) / self.stc.tstep))
            idx = max(0, min(idx, self.stc.data.shape[1] - 1))
        else:
            idx = 0
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

        ctrl_layout.addWidget(QtWidgets.QLabel("Opacity"))
        ctrl_layout.addWidget(self.opacity_slider)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(QtWidgets.QLabel("Time"))
        ctrl_layout.addWidget(self.time_slider)

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

        self.cortex_lh = self.plotter.add_mesh(
            lh, color="lightgray", opacity=0.5, name="lh"
        )
        self.cortex_rh = self.plotter.add_mesh(
            rh, color="lightgray", opacity=0.5, name="rh"
        )

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

    def _update_opacity(self, value: int) -> None:
        alpha = max(0, min(100, int(value))) / 100
        for actor in (self.cortex_lh, self.cortex_rh):
            actor.GetProperty().SetOpacity(alpha)
        self.plotter.render()

    def _update_time(self, value: int) -> None:
        idx = max(0, min(int(value), self.stc.data.shape[1] - 1))
        data = self.stc.data[:, idx]
        n_lh = len(self.stc.vertices[0])
        arr_lh = np.full(self.heat_lh.n_points, np.nan)
        arr_rh = np.full(self.heat_rh.n_points, np.nan)
        arr_lh[self.stc.vertices[0]] = data[:n_lh]
        arr_rh[self.stc.vertices[1]] = data[n_lh:]

        # Modern PyVista approach: modify mesh scalars in-place
        self.heat_lh.point_data["activation"] = arr_lh
        self.heat_rh.point_data["activation"] = arr_rh
        self.plotter.render()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="View a source estimate file")
    parser.add_argument("--stc", required=True, help="Base STC file path")
    parser.add_argument("--time-ms", type=float, help="Initial time in ms")
    args = parser.parse_args(argv)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    viewer = STCViewer(args.stc, args.time_ms)
    viewer.show()
    app.exec_()


if __name__ == "__main__":  # pragma: no cover - manual UI
    main()
