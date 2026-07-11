"""Qt worker for non-blocking mixed-model sensitivity simulation."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from Tools.Sensitivity_Analysis.lmm_simulation import (
    LmmSensitivityConfig,
    LmmSensitivityResult,
    LmmSimulationCancelled,
    calculate_lmm_sensitivity,
)

SimulationRunner = Callable[..., LmmSensitivityResult]


class LmmSensitivityWorker(QObject):
    """Run simulation work off the GUI thread and expose progress by signals."""

    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        config: LmmSensitivityConfig,
        *,
        runner: SimulationRunner = calculate_lmm_sensitivity,
    ) -> None:
        super().__init__()
        self._config = config
        self._runner = runner
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self._runner(
                self._config,
                progress=self.progress.emit,
                should_cancel=self._cancel_event.is_set,
            )
        except LmmSimulationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()


__all__ = ["LmmSensitivityWorker"]
