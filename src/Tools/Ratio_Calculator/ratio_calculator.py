"""Entry point for the Ratio Calculator PySide6 tool."""
from __future__ import annotations

# Allow running as a script
if __package__ is None:  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from pathlib import Path

from PySide6.QtWidgets import QApplication

from Main_App.PySide6_App.utils.theme import apply_light_palette
from Tools.Ratio_Calculator.PySide6 import create_ratio_calculator_window


def main() -> None:
    app = QApplication([])
    apply_light_palette(app)
    win = create_ratio_calculator_window(project_root=Path.cwd())
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
