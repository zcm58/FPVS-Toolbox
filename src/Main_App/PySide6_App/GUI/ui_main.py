# ui_main.py
""""UI initialization extracted from main_window.py."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QToolBar,
    QLabel,
    QWidget,
    QStackedWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QGridLayout,
    QRadioButton,
    QCheckBox,
    QButtonGroup,
    QScrollArea,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QFont

from .menu_bar import build_menu_bar


def init_ui(self) -> None:
    # Menu bar
    menu = build_menu_bar(self)
    self.setMenuBar(menu)

    # Top toolbar
    toolbar = QToolBar(self)
    toolbar.setMovable(False)
    toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
    self.addToolBar(Qt.TopToolBarArea, toolbar)
    self.lbl_debug = QLabel("DEBUG MODE ENABLED", self)
    self.lbl_debug.setStyleSheet("color: red;")
    self.lbl_debug.setVisible(self.settings.debug_enabled())
    toolbar.addWidget(self.lbl_debug)

    # Central stack
    self.stacked = QStackedWidget(self)
    self.setCentralWidget(self.stacked)

    # ===== Page 0: Landing =====
    landing = QWidget(self.stacked)
    lay0 = QVBoxLayout(landing)
    lay0.setContentsMargins(40, 40, 40, 40)

    title = QLabel("Welcome to the FPVS Toolbox!", landing)
    title_font = QFont()
    title_font.setPointSize(24)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setAlignment(Qt.AlignCenter)

    self.btn_create_project = QPushButton("Create New Project", landing)
    self.btn_open_project = QPushButton("Open Existing Project", landing)
    button_font = QFont()
    button_font.setPointSize(14)
    for btn in (self.btn_create_project, self.btn_open_project):
        btn.setFont(button_font)
        btn.setFixedHeight(60)
        btn.setMinimumWidth(200)
        btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn.setStyleSheet("QPushButton { padding: 12px 24px; }")

    btn_row = QHBoxLayout()
    btn_row.setSpacing(20)
    btn_row.setAlignment(Qt.AlignCenter)
    btn_row.addWidget(self.btn_create_project)
    btn_row.addWidget(self.btn_open_project)

    lay0.addWidget(title)
    lay0.addStretch(1)
    lay0.addLayout(btn_row)
    lay0.addStretch(1)

    self.stacked.addWidget(landing)

    # ===== Page 1: Main UI =====
    # Layout: [ sidebar | (slideSpacer | content) ]
    page1 = QWidget(self.stacked)
    page1_h = QHBoxLayout(page1)
    page1_h.setContentsMargins(0, 0, 0, 0)
    page1_h.setSpacing(0)

    # Left: permanent sidebar placeholder (populated by sidebar.init_sidebar)
    self.sidebar = QWidget(page1)
    self.sidebar.setObjectName("sidebar")
    self.sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    self.sidebar.setMinimumWidth(200)
    self.sidebar.setContentsMargins(0, 0, 0, 0)
    page1_h.addWidget(self.sidebar)

    # Right: wrapper for slide-in animation
    self.content_wrapper = QWidget(page1)
    wrapper_h = QHBoxLayout(self.content_wrapper)
    wrapper_h.setContentsMargins(0, 0, 0, 0)
    wrapper_h.setSpacing(0)

    # Spacer we animate (shrinks from full width -> 0)
    self.slideSpacer = QWidget(self.content_wrapper)
    self.slideSpacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    self.slideSpacer.setMaximumWidth(0)  # will be set at runtime before anim
    wrapper_h.addWidget(self.slideSpacer)

    # Actual content panel
    container = QWidget(self.content_wrapper)
    container.setObjectName("MainContent")
    main_layout = QVBoxLayout(container)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(12)

    # Header bar (styled in main_window via #HeaderBar)
    header = QWidget(container)
    header.setObjectName("HeaderBar")
    h_lay = QHBoxLayout(header)
    h_lay.setContentsMargins(0, 0, 0, 0)
    self.lbl_currentProject = QLabel("Current Project: None", header)
    h_lay.addWidget(self.lbl_currentProject)
    h_lay.addStretch(1)
    main_layout.addWidget(header)

    # Processing Options
    grp_proc = QGroupBox("Processing Options", container)
    gl = QGridLayout(grp_proc)
    gl.addWidget(QLabel("Mode:"), 0, 0)
    self.rb_single = QRadioButton("Single File", grp_proc)
    self.rb_batch = QRadioButton("Batch Folder", grp_proc)
    gl.addWidget(self.rb_single, 0, 1)
    gl.addWidget(self.rb_batch, 0, 2)
    self.cb_loreta = QCheckBox("Run LORETA during processing?", grp_proc)
    gl.addWidget(self.cb_loreta, 1, 0, 1, 3)
    self.mode_group = QButtonGroup(self)
    self.mode_group.setExclusive(True)
    self.mode_group.addButton(self.rb_single)
    self.mode_group.addButton(self.rb_batch)
    self.rb_single.toggled.connect(
        lambda checked: checked and self._on_mode_changed("single")
    )
    self.rb_batch.toggled.connect(
        lambda checked: checked and self._on_mode_changed("batch")
    )
    main_layout.addWidget(grp_proc)

    # Load saved processing options
    mode = self.settings.get("processing", "mode", "batch").lower()
    (self.rb_batch if mode == "batch" else self.rb_single).setChecked(True)
    self.cb_loreta.setChecked(
        self.settings.get("processing", "run_loreta", "False").lower() == "true"
    )

    # Preprocessing placeholder
    placeholder = QLabel("⚙️ Configure preprocessing in Settings", container)
    placeholder.setAlignment(Qt.AlignCenter)
    placeholder.setStyleSheet("color: #CCCCCC; font-style: italic;")
    main_layout.addWidget(placeholder)

    # Event Map group
    grp_event = QGroupBox("Event Map (Condition Label → Numerical ID)", container)
    vlay = QVBoxLayout(grp_event)
    scroll = QScrollArea(grp_event)
    scroll.setWidgetResizable(True)
    self.event_container = QWidget()
    self.event_layout = QVBoxLayout(self.event_container)
    self.event_layout.setSpacing(2)
    scroll.setWidget(self.event_container)
    vlay.addWidget(scroll)
    btns = QHBoxLayout()
    self.btn_detect = QPushButton("Detect Trigger IDs", grp_event)
    self.btn_add_row = QPushButton("+ Add Condition", grp_event)
    btns.addWidget(self.btn_detect)
    btns.addWidget(self.btn_add_row)
    vlay.addLayout(btns)
    main_layout.addWidget(grp_event)

    # Start + Progress Row
    action_row = QHBoxLayout()
    action_row.setSpacing(16)

    self.btn_start = QPushButton(container)
    self.progress_bar = QProgressBar(container)

    self.btn_start.setText("Start Processing")
    self.btn_start.setMinimumSize(150, 36)
    self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setFormat("%p%")
    self.progress_bar.setAlignment(Qt.AlignCenter)
    self.progress_bar.setFixedHeight(self.btn_start.sizeHint().height())
    self.progress_bar.setStyleSheet(
        """
        QProgressBar { min-height: 36px; text-align: center; }
        QProgressBar::chunk { background-color: #0BBF00; }
        """
    )

    action_row.addWidget(self.btn_start)
    action_row.addWidget(self.progress_bar, 1)
    main_layout.addLayout(action_row)

    # Progress animation hook (unchanged)
    self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
    self._progress_anim.setDuration(200)
    self._progress_anim.valueChanged.connect(self.progress_bar.setValue)
    self.processor.progressChanged.connect(self._animate_progress_to)

    # Populate saved event map rows
    saved_pairs = self.settings.get_event_pairs()
    if saved_pairs:
        for label, ident in saved_pairs:
            self.add_event_row(label, ident)
    else:
        self.add_event_row()

    # Log group
    grp_log = QGroupBox("Log", container)
    lay_log = QVBoxLayout(grp_log)
    self.text_log = QTextEdit(grp_log)
    self.text_log.setReadOnly(True)
    lay_log.addWidget(self.text_log)
    main_layout.addWidget(grp_log)

    # Finish RIGHT side
    wrapper_h.addWidget(container, 1)
    page1_h.addWidget(self.content_wrapper, 1)

    # Expose references used elsewhere
    self.page1_container = container
    self.page1_right = container          # for older code paths
    self.page1_wrapper = self.content_wrapper  # used by the new slide-in
    self.homeWidget = container

    self.stacked.addWidget(page1)

    # Wire buttons
    self.btn_add_row.clicked.connect(lambda: self.add_event_row())
    self.btn_detect.clicked.connect(self.detect_trigger_ids)

    # Sync select button label
    self._update_select_button_text()
