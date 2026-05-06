from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

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
        font = QFont()
        font.setPointSize(12)
        font.setWeight(QFont.DemiBold)
        self.titleLabel.setFont(font)

        layout.addWidget(self.titleLabel)
        layout.addStretch(1)
