from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Optional, Tuple, List

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QProgressBar, QTextEdit, QHBoxLayout, QMessageBox, QWidget, QSpinBox
)

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, Future

from Main_App import SettingsManager
from . import worker

# Windows-friendly: ensure spawn
mp.set_start_method("spawn", force=True)


class SourceLocalizationDialog(QDialog):
    """Run oddball eLORETA processing and view later as a 3D movie."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Source Localization (Oddball eLORETA)")
        self.setMinimumWidth(720)

        self._future: Optional[Future] = None
        self._executor: Optional[ProcessPoolExecutor] = None
        self._queue: Optional[mp.queues.Queue] = None
        self._poller = QTimer(self)
        self._poller.setInterval(80)
        self._poller.timeout.connect(self._drain_queue)

        self._build_ui()
        self._load_defaults()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        grid = QGridLayout()
        row = 0

        # FIF (epochs) path
        grid.addWidget(QLabel("Input FIF (epochs):"), row, 0, Qt.AlignRight)
        self.in_edit = QLineEdit()
        btn_in = QPushButton("Browse…")
        btn_in.clicked.connect(self._pick_fif)
        grid.addWidget(self.in_edit, row, 1)
        grid.addWidget(btn_in, row, 2)
        row += 1

        # Output folder
        grid.addWidget(QLabel("Output folder:"), row, 0, Qt.AlignRight)
        self.out_edit = QLineEdit()
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(self._pick_out)
        grid.addWidget(self.out_edit, row, 1)
        grid.addWidget(btn_out, row, 2)
        row += 1

        # SNR
        grid.addWidget(QLabel("SNR:"), row, 0, Qt.AlignRight)
        self.snr_edit = QLineEdit("3.0")
        self.snr_edit.setPlaceholderText("e.g., 3.0")
        grid.addWidget(self.snr_edit, row, 1)
        row += 1

        # Threshold (fraction 0..1; applied against abs-max in viewer)
        grid.addWidget(QLabel("Threshold (0–1):"), row, 0, Qt.AlignRight)
        self.thr_edit = QLineEdit("0.0")
        self.thr_edit.setPlaceholderText("0 disables threshold")
        grid.addWidget(self.thr_edit, row, 1)
        row += 1

        # Post-stim window end (ms)
        grid.addWidget(QLabel("Post-stimulus window end (ms):"), row, 0, Qt.AlignRight)
        self.tpost_spin = QSpinBox()
        self.tpost_spin.setRange(100, 1000)
        self.tpost_spin.setSingleStep(50)
        self.tpost_spin.setValue(700)
        grid.addWidget(self.tpost_spin, row, 1)
        row += 1

        # Initial viewer time (ms)
        grid.addWidget(QLabel("Viewer initial time (ms):"), row, 0, Qt.AlignRight)
        self.tview_spin = QSpinBox()
        self.tview_spin.setRange(0, 1000)
        self.tview_spin.setSingleStep(10)
        self.tview_spin.setValue(150)
        grid.addWidget(self.tview_spin, row, 1)
        row += 1

        root.addLayout(grid)

        # Buttons
        hb = QHBoxLayout()
        self.run_btn = QPushButton("Run eLORETA")
        self.run_btn.clicked.connect(self._run)
        self.view_btn = QPushButton("Open Viewer")
        self.view_btn.setEnabled(False)
        self.view_btn.clicked.connect(self._open_viewer)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        hb.addWidget(self.run_btn)
        hb.addWidget(self.view_btn)
        hb.addStretch(1)
        hb.addWidget(self.close_btn)
        root.addLayout(hb)

        # Progress + logs
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        root.addWidget(self.prog)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        # State
        self._stc_path: Optional[str] = None

    def _load_defaults(self) -> None:
        s = SettingsManager()
        self.in_edit.setText(s.get("paths", "last_epochs", ""))
        self.out_edit.setText(s.get("paths", "last_output", ""))

        # Threshold default from settings if present
        try:
            thr = float(s.get("loreta", "loreta_threshold", "0.0"))
        except ValueError:
            thr = 0.0
        self.thr_edit.setText(str(thr))

        try:
            snr = float(s.get("loreta", "loreta_snr", "3.0"))
        except ValueError:
            snr = 3.0
        self.snr_edit.setText(str(snr))

        # Tpost default: clamp to oddball cycle if configured
        try:
            odd_f = float(s.get("analysis", "oddball_freq", "1.2"))
            max_ms = int(max(100, min(1000, (1.0 / odd_f - 0.05) * 1000)))
            self.tpost_spin.setMaximum(max_ms)
            self.tpost_spin.setValue(min(self.tpost_spin.value(), max_ms))
        except Exception:
            pass

    # ---------- Actions ----------

    @Slot()
    def _pick_fif(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FIF epochs file", self.in_edit.text(), "FIF files (*.fif)"
        )
        if path:
            self.in_edit.setText(path)
            SettingsManager().set("paths", "last_epochs", path)

    @Slot()
    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.out_edit.text() or str(Path.cwd())
        )
        if path:
            self.out_edit.setText(path)
            SettingsManager().set("paths", "last_output", path)

    @Slot()
    def _run(self) -> None:
        if self._future is not None:
            return  # guard re-entrancy

        fif_path = self.in_edit.text().strip()
        out_dir = self.out_edit.text().strip()
        if not fif_path or not Path(fif_path).is_file():
            QMessageBox.critical(self, "Error", "Valid FIF epochs file required.")
            return
        if not fif_path.endswith("-epo.fif"):
            QMessageBox.critical(self, "Error", "Please select an epochs FIF (-epo.fif).")
            return
        if not out_dir:
            QMessageBox.critical(self, "Error", "Select an output folder.")
            return

        try:
            snr = float(self.snr_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "SNR must be a number.")
            return

        try:
            thr = float(self.thr_edit.text())
        except ValueError:
            thr = 0.0

        tpost_ms = int(self.tpost_spin.value())

        # Prepare worker
        ctx = mp.get_context("spawn")
        self._queue = ctx.Manager().Queue()
        self._executor = ProcessPoolExecutor(max_workers=1, mp_context=ctx)

        # Kick off processing (oddball pipeline only)
        self._future = self._executor.submit(
            worker.run_localization_worker,
            fif_path,
            out_dir,
            method="eLORETA",
            threshold=thr,
            alpha=0.5,  # viewer-only
            hemi="split",
            low_freq=None,
            high_freq=None,
            harmonics=[],            # removed in oddball path
            snr=snr,
            oddball=True,            # only oddball is supported
            export_rois=False,
            baseline=None,           # use SettingsManager baseline inside runner
            time_window=(0.0, tpost_ms / 1000.0),  # 0..Tpost
            queue=self._queue,
        )
        self._poller.start()
        self._set_running(True)
        self._append_log("Started oddball eLORETA…")

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.view_btn.setEnabled(False if running else (self._stc_path is not None))

    def _append_log(self, msg: str) -> None:
        self.log.append(msg)

    @Slot()
    def _drain_queue(self) -> None:
        if self._queue is None:
            return
        try:
            while True:
                msg = self._queue.get_nowait()
                t = msg.get("type")
                if t == "progress":
                    val = float(msg.get("value", 0.0))
                    self.prog.setValue(int(val * 100))
                elif t == "log":
                    self._append_log(msg.get("message", ""))
                elif t == "error":
                    self._append_log(f"ERROR: {msg.get('message')}")
                elif t == "done":
                    self._stc_path = msg.get("stc_path")
        except Exception:
            pass

        if self._future and self._future.done():
            self._poller.stop()
            self._handle_done()

    def _handle_done(self) -> None:
        self._set_running(False)
        err_text = None
        try:
            _result_path, _ = self._future.result()
            if not self._stc_path:
                self._stc_path = _result_path
        except Exception as e:
            err_text = str(e)

        # cleanup executor
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._future = None

        if err_text:
            QMessageBox.critical(self, "Error", err_text)
        else:
            self._append_log("Done.")
            self.view_btn.setEnabled(bool(self._stc_path))

    @Slot()
    def _open_viewer(self) -> None:
        if not self._stc_path:
            return
        # spawn PySide6 viewer in-process
        from .pyqt_viewer import launch_viewer
        launch_viewer(self._stc_path, float(self.tview_spin.value()))

    # ---------- lifecycle ----------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._executor:
            # don't block; let the future finish in background process if running
            try:
                self._executor.shutdown(wait=False, cancel_futures=False)
            except Exception:
                pass
            self._executor = None
        self._future = None
        super().closeEvent(event)
