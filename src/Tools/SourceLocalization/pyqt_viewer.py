from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6 import QtWidgets, QtCore
import mne

# Make project imports resolvable when the module is run directly
SRC_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC_PATH))

from Tools.SourceLocalization.data_utils import _resolve_subjects_dir
from Tools.SourceLocalization.backend_utils import _ensure_pyvista_backend
from Tools.SourceLocalization.logging_utils import get_pkg_logger
from Main_App import SettingsManager

logger = logging.getLogger(__name__)
log = get_pkg_logger()

# Keep strong references so windows are not GC'd
_OPEN_VIEWERS: list[QtWidgets.QWidget] = []


def _safe_show(widget: QtWidgets.QWidget) -> None:
    log.debug("Calling .show() on %s", type(widget).__name__)
    widget.show()
    log.debug("Widget shown: %s", repr(widget))


class STCViewer(QtWidgets.QMainWindow):
    """Qt window for interactively viewing SourceEstimate files."""

    def __init__(self, stc_path: str, time_ms: Optional[float] = None) -> None:
        log.debug("ENTER STCViewer.__init__", extra={"path": stc_path})
        super().__init__()

        if SettingsManager().debug_enabled():
            log.debug(
                "STCViewer PySide6=%s Qt=%s",
                QtCore.__version__,
                QtCore.qVersion(),
            )

        self.setWindowTitle(os.path.basename(stc_path))

        # --- safe defaults (avoid race)
        self._global_vmax: float = 1.0
        self.cortex_lh = self.cortex_rh = None
        self.act_lh = self.act_rh = None
        self.heat_lh = self.heat_rh = None

        # Load STC
        try:
            log.debug("Loading STC", extra={"path": stc_path})
            self.stc = mne.read_source_estimate(stc_path)
            miss = []
            if not len(self.stc.vertices[0]):
                miss.append("lh")
            if not len(self.stc.vertices[1]):
                miss.append("rh")
            if miss:
                log.warning(
                    "STC missing hemisphere(s): %s",
                    ",".join(miss),
                    extra={"path": stc_path},
                )
        except Exception:
            log.exception("Failed to read STC", extra={"path": stc_path})
            raise

        self._setup_subjects()
        self._build_ui()
        self._load_surfaces()

        # Global abs-max for shared clim
        try:
            data = self._as_scalar_data(self.stc)
            self._global_vmax = float(np.abs(data).max()) or 1.0
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
        log.debug("EXIT STCViewer.__init__", extra={"path": stc_path})

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
        show_default = (
            SettingsManager()
            .get("visualization", "show_brain_mesh", "True")
            .lower()
            == "true"
        )
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
        log.debug("ENTER _load_surfaces", extra={"subject": subject})

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

        # Heat maps
        self.heat_lh = lh.copy()
        self.heat_rh = rh.copy()
        self.heat_lh.point_data["activation"] = np.full(lh.n_points, np.nan)
        self.heat_rh.point_data["activation"] = np.full(rh.n_points, np.nan)

        clim = (0.0, self._global_vmax)

        self.act_lh = self.plotter.add_mesh(
            self.heat_lh,
            scalars="activation",
            cmap="hot",
            nan_opacity=0.0,
            name="act_lh",
            clim=clim,
        )
        self.act_rh = self.plotter.add_mesh(
            self.heat_rh,
            scalars="activation",
            cmap="hot",
            nan_opacity=0.0,
            name="act_rh",
            clim=clim,
        )
        self.plotter.add_scalar_bar(title="|Source| Amplitude", n_colors=8)
        log.debug("EXIT _load_surfaces", extra={"subject": subject})

    # ---- helpers & interactions

    def _index_for_time(self, sec: float) -> int:
        return int(round((sec - self.stc.tmin) / self.stc.tstep))

    @staticmethod
    def _as_scalar_data(stc: mne.SourceEstimate) -> np.ndarray:
        """Return a (n_verts_total, n_times) scalar view for scalar or vector STC."""
        data = stc.data
        # Vector STC handling: try common layouts robustly.
        if getattr(stc, "is_vector", False) or data.ndim == 3 or (
            data.ndim == 2
            and data.shape[0] == 3 * (len(stc.vertices[0]) + len(stc.vertices[1]))
        ):
            try:
                # MNE Vector STC often (n_verts, n_times, 3)
                if data.ndim == 3 and data.shape[2] == 3:
                    return np.linalg.norm(data, axis=2)
                # Or flattened (3*n_verts, n_times) as [x,y,z] blocks
                n = len(stc.vertices[0]) + len(stc.vertices[1])
                reshaped = data.reshape(3, n, -1)  # (3, n_verts, n_times)
                return np.linalg.norm(reshaped, axis=0)
            except Exception:
                pass
        return data

    def _update_opacity(self, value: int) -> None:
        opacity = max(0.0, min(float(value) / 100.0, 1.0))
        if self.cortex_lh is not None:
            self.cortex_lh.GetProperty().SetOpacity(opacity)
        if self.cortex_rh is not None:
            self.cortex_rh.GetProperty().SetOpacity(opacity)
        self.plotter.render()

    def _toggle_cortex(self, state: int) -> None:
        visible = state == QtCore.Qt.Checked
        if self.cortex_lh is not None:
            self.cortex_lh.SetVisibility(visible)
        if self.cortex_rh is not None:
            self.cortex_rh.SetVisibility(visible)
        self.plotter.render()

    def _update_time(self, value: int) -> None:
        if self.stc is None:
            return
        idx = max(0, min(int(value), self.stc.data.shape[1] - 1))
        scalar = self._as_scalar_data(self.stc)
        frame = np.abs(scalar[:, idx])  # magnitude for sequential cmap

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
    log.debug("ENTER launch_viewer", extra={"path": stc_path})
    try:
        os.environ.setdefault("QT_API", "pyside6")
        _ensure_pyvista_backend()

        # High-DPI attributes must be set **before** creating the app
        own_app = False
        app = QtWidgets.QApplication.instance()
        if app is None:
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
            app = QtWidgets.QApplication(sys.argv)
            own_app = True

        viewer = STCViewer(stc_path, time_ms)
        _OPEN_VIEWERS.append(viewer)   # keep strong ref
        _safe_show(viewer)
        log.info("Viewer opened", extra={"path": stc_path})

        if own_app:
            app.exec()
    except Exception:
        log.exception("Failed to open viewer", extra={"path": stc_path})
        raise
    finally:
        log.debug("EXIT launch_viewer", extra={"path": stc_path})


def diagnose_open_stc(path: str) -> dict[str, object]:
    """Quickly check if an STC can be loaded and minimally visualized."""
    info: dict[str, object] = {"ok": False, "error": None}
    p = Path(path)
    log.info(
        "diagnose_open_stc",
        extra={
            "path": path,
            "exists": p.exists(),
            "suffix": p.suffix,
            "size": p.stat().st_size if p.exists() else 0,
        },
    )
    try:
        mne.read_source_estimate(path)
        pv.Plotter(off_screen=True).close()
        info["ok"] = True
    except Exception as err:
        info["error"] = str(err)
        log.exception("diagnose_open_stc_failed", extra={"path": path})
    return info
