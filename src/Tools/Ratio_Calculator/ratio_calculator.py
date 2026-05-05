"""PySide6 GUI for the Ratio Calculator tool."""
from __future__ import annotations

if __package__ is None:  # pragma: no cover - executed when run as script
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from Main_App.gui.theme import apply_fpvs_theme
from Tools.Ratio_Calculator.gui import RatioCalculatorWindow


def main() -> None:
    app = QApplication([])
    apply_fpvs_theme(app)
    win = RatioCalculatorWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
