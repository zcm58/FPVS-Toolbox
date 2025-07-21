from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6 import QtWidgets


class MainWindow(QtWidgets.QMainWindow):
    """Minimal window displaying a blank label."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FPVS Toolbox")

        label = QtWidgets.QLabel("")
        label.setAlignment(Qt.AlignCenter)


        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.addWidget(label)
        self.setCentralWidget(central)


def main() -> None:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
