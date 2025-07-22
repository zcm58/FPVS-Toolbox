# src/Main_App/GUI/main_window.py

from __future__ import annotations
from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout
from Main_App.GUI.menu_bar import build_menu_bar
from Main_App.GUI.settings_panel import SettingsPanel

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FPVS Toolbox")
        self.setMinimumSize(800, 600)

        # install menu
        menu_bar = build_menu_bar(self)
        self.setMenuBar(menu_bar)

        # central widget
        label = QtWidgets.QLabel("Welcome to the FPVS Toolbox!")
        label.setAlignment(Qt.AlignCenter)
        central = QtWidgets.QWidget()
        layout  = QtWidgets.QVBoxLayout(central)
        layout.addWidget(label)
        self.setCentralWidget(central)

    # ─────── placeholder stubs ─────────────────────────────
    def open_settings_window(self) -> None:
        # 1) create modal dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setModal(True)

        # 2) layout for the panel
        dlg_layout = QVBoxLayout(dlg)

        # 3) instantiate your SettingsPanel, passing self or your controller
        panel = SettingsPanel(self)
        dlg_layout.addWidget(panel)

        # 4) wire the panel signals to close (and optionally save)
        panel.settings_saved.connect(dlg.accept)
        panel.settings_canceled.connect(dlg.reject)

        # 5) run the dialog
        dlg.exec()

    def check_for_updates(self):
        print("CHECK UPDATES (stub)")

    def quit(self):
        self.close()

    def open_stats_analyzer(self):
        print("STATS ANALYZER (stub)")

    def open_image_resizer(self):
        print("IMAGE RESIZER (stub)")

    def open_plot_generator(self):
        print("PLOT GENERATOR (stub)")

    def open_advanced_analysis_window(self):
        print("ADV ANALYSIS (stub)")

    def show_relevant_publications(self):
        print("SHOW PUBLICATIONS (stub)")

    def show_about_dialog(self):
        QtWidgets.QMessageBox.information(self, "About", "FPVS Toolbox\nVersion X.Y")

def main() -> None:
    app    = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()

if __name__ == "__main__":
    main()
