"""PySide6 GUI for generating SNR/BCA line plots from Excel files."""
from __future__ import annotations

# Allow running this module directly by ensuring the package root is on sys.path
if __package__ is None:  # pragma: no cover - executed when run as script
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from Tools.Plot_Generator.worker import _Worker
from Tools.Plot_Generator.gui import PlotGeneratorWindow

__all__ = ["_Worker", "PlotGeneratorWindow", "main"]


def main() -> None:
    app = QApplication([])
    win = PlotGeneratorWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
