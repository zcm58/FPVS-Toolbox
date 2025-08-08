from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

class HeaderBar(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        # Give it a stable object name and ensure the background gets painted.
        self.setObjectName("HeaderBar")
        self.setAttribute(Qt.WA_StyledBackground, True)  # <- ensures bg color is drawn

        # Style just this widget (not every QWidget)
        self.setStyleSheet("""
            #HeaderBar {
                background-color: #2C2C2C;       /* charcoal */
                border-bottom: 2px solid #0078D4; /* Windows blue accent */
            }
            #HeaderBar QLabel {
                color: white;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(0)

        self.titleLabel = QLabel(title, self)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.titleLabel.setFont(font)

        layout.addWidget(self.titleLabel)
        layout.addStretch(1)
