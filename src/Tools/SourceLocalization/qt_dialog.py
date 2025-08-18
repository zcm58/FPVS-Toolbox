# src/Tools/SourceLocalization/qt_dialog.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Tuple
import sys, queue, multiprocessing as mp, os, re

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QFileDialog, QDoubleSpinBox, QSpinBox, QProgressBar, QTextEdit, QGroupBox,
    QWidget, QMessageBox, QCheckBox, QLabel
)
from PySide6.QtGui import QAction  # project rule

from Main_App import SettingsManager
from . import worker
from .logging_utils import get_pkg_logger

log = get_pkg_logger()

DEFAULT_WORKERS = 7  # auto-capped by CPU below


class _OpGuard:
    def __init__(self) -> None: self._busy = False
    def start(self) -> bool:
        if self._busy: return False
        self._busy = True; return True
    def done(self) -> None: self._busy = False


def _f(section: str, key: str, default: float) -> float:
    try: return float(SettingsManager().get(section, key, str(default)))
    except Exception: return float(default)

def _i(section: str, key: str, default: int) -> int:
    try: return int(float(SettingsManager().get(section, key, str(default))))
    except Exception: return int(default)

def _wrap(layout: QHBoxLayout) -> QWidget:
    w = QWidget(); w.setLayout(layout); return w

def _safe_rel(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except Exception:
        return Path(path.name)


class SourceLocalizationDialog(QDialog):
    """Run oddball e/sLORETA on one or many *-epo.fif files (batch/parallel)."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Source Localization (Oddball e/sLORETA)")
        self.setMinimumSize(QSize(780, 540))
        self.setModal(True)
        self.setProperty("class", "dialog-surface")

        # prove correct Qt import origin (project rule, no-ops safely)
        self._dummy_action: QAction = QAction(self)

        self._guard = _OpGuard()
        self._timer = QTimer(self, interval=75)
        self._timer.timeout.connect(self._poll_queues)

        root = QVBoxLayout(self)

        # --- I/O
        io_box = QGroupBox("Input / Output"); io_box.setProperty("class", "panel")
        io = QFormLayout(io_box)

        self.in_edit = QLineEdit(); self.in_btn = QPushButton("Browse…")
        row1 = QHBoxLayout(); row1.addWidget(self.in_edit); row1.addWidget(self.in_btn)

        self.folder_edit = QLineEdit(); self.folder_btn = QPushButton("Batch parent folder…")
        row2 = QHBoxLayout(); row2.addWidget(self.folder_edit); row2.addWidget(self.folder_btn)

        self.out_edit = QLineEdit(); self.out_btn = QPushButton("Output root…")
        row3 = QHBoxLayout(); row3.addWidget(self.out_edit); row3.addWidget(self.out_btn)

        io.addRow("Input FIF (epochs):", _wrap(row1))
        io.addRow("Or parent of condition subfolders:", _wrap(row2))
        io.addRow("Output root folder:", _wrap(row3))

        # --- Params
        p_box = QGroupBox("Parameters"); p_box.setProperty("class", "panel")
        p = QFormLayout(p_box)

        self.snr = QDoubleSpinBox(minimum=1.0, maximum=20.0, decimals=2, singleStep=0.1)
        self.snr.setValue(_f("loreta", "loreta_snr", 3.0))
        self.snr.setToolTip("Inverse SNR for regularization (lambda² = 1 / SNR²).")

        self.thr = QDoubleSpinBox(minimum=0.0, maximum=1.0, decimals=3, singleStep=0.01)
        self.thr.setValue(_f("loreta", "loreta_threshold", 0.05))
        self.thr.setToolTip("Relative threshold: values below (thr × max|STC|) → 0.")

        self.t_end_ms = QSpinBox(minimum=50, maximum=3000, singleStep=10)
        self.t_end_ms.setValue(_i("visualization", "time_window_end_ms", 700))
        self.t_end_ms.setToolTip("Post-stimulus window end (ms) for STC export.")

        self.viewer_ms = QSpinBox(minimum=0, maximum=3000, singleStep=10)
        self.viewer_ms.setValue(_i("visualization", "time_index_ms", 150))
        self.viewer_ms.setToolTip("Initial time (ms) when opening the viewer.")

        self.ids_edit = QLineEdit()
        self.ids_edit.setPlaceholderText("Oddball IDs, e.g., 55  (comma/space/comma-separated; blank = 55)")
        # Default to 55 if no saved value
        saved_ids = SettingsManager().get("analysis", "oddball_event_ids", "").strip()
        self.ids_edit.setText(saved_ids or "55")
        self.ids_edit.setToolTip("Comma/space/semicolon separated event IDs. For FPVS oddballs use 55.")

        p.addRow("SNR:", self.snr)
        p.addRow("Threshold (0–1):", self.thr)
        p.addRow("Post-stimulus window end (ms):", self.t_end_ms)
        p.addRow("Viewer initial time (ms):", self.viewer_ms)
        p.addRow("Oddball event IDs:", self.ids_edit)

        # --- Actions
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run eLORETA")
        self.view_btn = QPushButton("Open Viewer")
        self.close_btn = QPushButton("Close")
        btn_row.addWidget(self.run_btn); btn_row.addWidget(self.view_btn)
        btn_row.addStretch(1); btn_row.addWidget(self.close_btn)

        # --- Progress + log
        self.progress = QProgressBar(textVisible=True); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.log = QTextEdit(readOnly=True)

        root.addWidget(io_box)
        root.addWidget(p_box)
        root.addLayout(btn_row)
        root.addWidget(self.progress)
        root.addWidget(self.log)

        # Wire
        self.in_btn.clicked.connect(self._pick_fif)
        self.folder_btn.clicked.connect(self._pick_folder)
        self.out_btn.clicked.connect(self._pick_dir)
        self.run_btn.clicked.connect(self._run)
        self.view_btn.clicked.connect(self._open_viewer)
        self.close_btn.clicked.connect(self.reject)

        # State
        self._jobs: List[Tuple[str, "mp.managers.BaseProxy", "object"]] = []
        self._managers: List["mp.managers.SyncManager"] = []
        self._pools: List["object"] = []
        self._completed = 0
        self._last_stc_base: Optional[str] = None

        self._apply_defaults_from_settings()
        self._auto_fill_parent_from_last_file()

    # ----- helpers
    def _apply_defaults_from_settings(self) -> None:
        s = SettingsManager()
        self.in_edit.setText(s.get("loreta", "last_epochs_path", ""))
        self.folder_edit.setText(s.get("loreta", "last_epochs_folder", ""))
        self.out_edit.setText(s.get("loreta", "last_out_dir", ""))

    def _persist_defaults(self) -> None:
        s = SettingsManager()
        if self.in_edit.text(): s.set("loreta", "last_epochs_path", self.in_edit.text())
        if self.folder_edit.text(): s.set("loreta", "last_epochs_folder", self.folder_edit.text())
        if self.out_edit.text(): s.set("loreta", "last_out_dir", self.out_edit.text())
        s.set("analysis", "oddball_event_ids", self.ids_edit.text())
        try: s.save()
        except Exception: pass

    def _auto_fill_parent_from_last_file(self) -> None:
        """If we have a last epochs path, set the parent '...\\.fif files' folder automatically."""
        if self.folder_edit.text():
            return
        p = self.in_edit.text().strip()
        if not p:
            p = SettingsManager().get("loreta", "last_epochs_path", "")
        try:
            path = Path(p)
            if path.is_file() and path.name.endswith("-epo.fif"):
                parent = path.parent.parent
                if parent.exists():
                    self.folder_edit.setText(str(parent))
        except Exception:
            pass

    def _pick_fif(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select epochs FIF", self.in_edit.text(), "MNE epochs (*.fif)")
        if path:
            self.in_edit.setText(path)
            try:
                parent = Path(path).parent.parent
                if parent.exists():
                    self.folder_edit.setText(str(parent))
            except Exception:
                pass

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select parent folder containing condition subfolders",
                                                self.folder_edit.text() or str(Path.home()))
        if path: self.folder_edit.setText(path)

    def _pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output root", self.out_edit.text() or str(Path.home()))
        if path: self.out_edit.setText(path)

    def _gather_inputs(self, parent: Path) -> List[Path]:
        """Return all *-epo.fif under condition subfolders of `parent`."""
        if parent.is_file() and parent.name.endswith("-epo.fif"):
            return [parent]
        if parent.is_dir():
            return sorted(parent.rglob("*-epo.fif"))
        return []

    @staticmethod
    def _parse_ids(txt: str) -> List[int]:
        out: List[int] = []
        for tok in re.split(r"[,\s;]+", txt.strip()):
            if not tok:
                continue
            try:
                out.append(int(tok))
            except ValueError:
                continue
        return out

    @staticmethod
    def _default_workers() -> int:
        cpu = os.cpu_count() or 2
        return max(1, min(DEFAULT_WORKERS, max(1, cpu - 1)))

    # ----- run
    def _run(self) -> None:
        if not self._guard.start():
            QMessageBox.information(self, "Busy", "Processing already running."); return

        parent_or_file = Path(self.folder_edit.text().strip() or self.in_edit.text().strip())
        out_root = Path(self.out_edit.text().strip())
        if not parent_or_file.exists():
            QMessageBox.warning(self, "Input needed", "Pick a *-epo.fif or the parent folder containing them."); self._guard.done(); return
        if not self.out_edit.text().strip():
            QMessageBox.warning(self, "Output needed", "Select an output root."); self._guard.done(); return
        self._persist_defaults()

        files = self._gather_inputs(parent_or_file)
        if not files:
            QMessageBox.warning(self, "No files", "No *-epo.fif found under the selected folder."); self._guard.done(); return

        ids_override = self._parse_ids(self.ids_edit.text())
        self.progress.setValue(0); self.log.clear()
        self._jobs.clear(); self._managers.clear(); self._pools.clear()
        self._completed = 0; self._last_stc_base = None

        max_workers = self._default_workers()
        self._append(f"Starting {len(files)} file(s); workers={max_workers}")

        ctx = mp.get_context("spawn")
        mgr = ctx.Manager(); self._managers.append(mgr)
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx); self._pools.append(pool)

        parent_root = parent_or_file if parent_or_file.is_dir() else parent_or_file.parent.parent

        for fpath in files:
            rel_cond = _safe_rel(fpath.parent, parent_root)  # e.g., 'Green Fruit vs Green Veg'
            out_dir = (out_root / rel_cond).resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            q = mgr.Queue()
            stc_base = f"{Path(fpath).stem}_LORETA_fsavg"
            fut = pool.submit(
                worker.run_localization_worker,
                str(fpath), str(out_dir),
                method="eLORETA",
                threshold=float(self.thr.value()),
                alpha=0.5,
                hemi="both",
                low_freq=None, high_freq=None, harmonics=[],
                snr=float(self.snr.value()),
                oddball=True, export_rois=False,
                baseline=None,
                time_window=(0.0, float(self.t_end_ms.value())),  # ms; runner converts
                event_ids=ids_override,  # override per run (e.g., 55)
                stc_basename=stc_base,
                queue=q,
            )
            self._jobs.append((str(fpath), q, fut))

        self._timer.start()

    # ----- polling & progress
    def _poll_queues(self) -> None:
        total = len(self._jobs)
        done_count = self._completed
        in_progress_fraction = 0.0

        for fpath, q, fut in list(self._jobs):
            try:
                while True:
                    msg = q.get_nowait()
                    t = msg.get("type")
                    if t == "log":
                        self._append(f"[{Path(fpath).name}] {msg.get('message','')}")
                    elif t == "progress":
                        setattr(fut, "_fpvs_prog", float(msg.get("value", 0.0)))
                    elif t == "error":
                        self._append(f"[{Path(fpath).name}] ERROR: {msg.get('message','')}")
            except queue.Empty:
                pass

            if fut.done() and not getattr(fut, "_fpvs_done_mark", False):
                try:
                    base, _ = fut.result()
                    self._last_stc_base = base
                    self._append(f"[{Path(fpath).name}] Saved: {base}-lh.stc / -rh.stc")
                except Exception as e:
                    self._append(f"[{Path(fpath).name}] ERROR: {e!s}")
                setattr(fut, "_fpvs_done_mark", True)
                done_count += 1

        for _, _, fut in self._jobs:
            in_progress_fraction += float(getattr(fut, "_fpvs_prog", 0.0))
        overall = (done_count + in_progress_fraction) / max(1, total)
        self.progress.setValue(int(overall * 100))
        self._completed = done_count

        if done_count >= total:
            self._finish(error=False)

    def _finish(self, *, error: bool) -> None:
        self._timer.stop()
        self._guard.done()
        for p in self._pools:
            try: p.shutdown(wait=False, cancel_futures=False)
            except Exception: pass
        for m in self._managers:
            try: m.shutdown()
            except Exception: pass
        if not error:
            self._append("All jobs finished.")

    def _append(self, line: str) -> None:
        self.log.append(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ----- viewer
    # ----- viewer
    def _open_viewer(self) -> None:
        def _mod_val(mod):
            try:
                return int(mod)  # type: ignore[arg-type]
            except Exception:
                try:
                    return int(mod.value)  # type: ignore[attr-defined]
                except Exception:
                    return str(mod)

        pre_state = {
            "isModal": self.isModal(),
            "windowModality": _mod_val(self.windowModality()),
            "wa_show_modal": self.testAttribute(Qt.WA_ShowModal),
        }
        pre_state["in_exec_loop"] = bool(
            pre_state["isModal"] or pre_state["wa_show_modal"]
        )
        log.debug("ENTER _open_viewer", extra=pre_state)
        base = self._last_stc_base or ""
        opts = QFileDialog.Options()
        # Use Qt's own dialog to avoid Windows native modality quirks
        opts |= QFileDialog.DontUseNativeDialog
        log.debug("stc_file_dialog", extra={"native": False})
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open STC (pick -lh.stc or -rh.stc)",
            base,
            "MNE STC (*.stc)",
            options=opts,
        )
        if not path:
            log.debug("EXIT _open_viewer (cancel)")
            return

        log.debug("Selected STC", extra={"path": path})
        try:
            from .pyqt_viewer import launch_viewer
            launch_viewer(path, time_ms=float(self.viewer_ms.value()))

            # If this dialog is running with exec() (application-modal),
            # it will block input to the new viewer. Make it modeless by
            # ending the modal loop RIGHT AFTER viewer launch.
            try:
                self.setModal(False)
                self.setWindowModality(Qt.NonModal)
            except Exception:
                pass
            # End modal event loop without tearing down immediately.
            # Using a singleShot avoids reentrancy issues.
            QTimer.singleShot(0, lambda: self.done(0))

        except Exception as e:
            log.exception("Failed to open viewer", extra={"path": path})
            self._append(f"ERROR: {e!s}")
            QMessageBox.critical(self, "Viewer error", str(e))
        finally:
            post_state = {
                "path": path,
                "isModal": self.isModal(),
                "windowModality": _mod_val(self.windowModality()),
                "wa_show_modal": self.testAttribute(Qt.WA_ShowModal),
            }
            post_state["in_exec_loop"] = bool(
                post_state["isModal"] or post_state["wa_show_modal"]
            )
            log.debug("EXIT _open_viewer", extra=post_state)
