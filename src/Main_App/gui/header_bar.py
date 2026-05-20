from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from Main_App.gui.typography import apply_font_role
from .style_tokens import build_header_bar_stylesheet

class HeaderBar(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        # Give it a stable object name and ensure the background gets painted.
        self.setObjectName("HeaderBar")
        self.setAttribute(Qt.WA_StyledBackground, True)  # <- ensures bg color is drawn

        # Style just this widget (not every QWidget)
        self.setStyleSheet(build_header_bar_stylesheet())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(0)

        self.titleLabel = QLabel(title, self)
        apply_font_role(self.titleLabel, "project_title")

        layout.addWidget(self.titleLabel)
        layout.addStretch(1)
