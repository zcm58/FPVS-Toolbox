"""PySide6 GUI for the Individual Detectability tool."""
from __future__ import annotations

if __package__ is None:  # pragma: no cover - executed when run as script
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from Main_App.PySide6_App.utils.theme import apply_light_palette
from Tools.Individual_Detectability.main_window import IndividualDetectabilityWindow


def main() -> None:
    app = QApplication([])
    apply_light_palette(app)
    win = IndividualDetectabilityWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
