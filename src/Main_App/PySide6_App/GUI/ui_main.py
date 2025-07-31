"""UI initialization extracted from main_window.py."""
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
    QStatusBar,
    QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QPropertyAnimation



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

    # Stacked central widget
    self.stacked = QStackedWidget(self)
    self.setCentralWidget(self.stacked)

    # ----- Page 0: Landing -----
    landing = QWidget(self.stacked)
    lay0 = QVBoxLayout(landing)
    lay0.addStretch(1)
    self.btn_create_project = QPushButton("Create New Project", landing)
    self.btn_open_project = QPushButton("Open Existing Project", landing)
    lay0.addWidget(self.btn_create_project)
    lay0.addWidget(self.btn_open_project)
    lay0.addStretch(1)
    self.stacked.addWidget(landing)

    # ----- Page 1: Main UI -----
    container = QWidget(self.stacked)
    main_layout = QVBoxLayout(container)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(12)

    header = QWidget(container)
    header.setStyleSheet("background-color: #2A2A2A; padding: 8px;")
    h_lay = QHBoxLayout(header)
    h_lay.setContentsMargins(0, 0, 0, 0)
    self.lbl_currentProject = QLabel("Current Project: None", header)
    self.lbl_currentProject.setStyleSheet("color: white; font-weight: bold;")
    h_lay.addWidget(self.lbl_currentProject)
    h_lay.addStretch(1)
    main_layout.addWidget(header)

    # Processing Options group
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
    if mode == "batch":
        self.rb_batch.setChecked(True)
    else:
        self.rb_single.setChecked(True)

    loreta_enabled = (
        self.settings.get("processing", "run_loreta", "False").lower() == "true"
    )
    self.cb_loreta.setChecked(loreta_enabled)

    # Preprocessing parameters have moved to Settings. Show placeholder
    placeholder = QLabel("⚙️ Configure preprocessing in Settings", container)
    placeholder.setAlignment(Qt.AlignCenter)
    placeholder.setStyleSheet("color: #CCCCCC; font-style: italic;")
    main_layout.addWidget(placeholder)

    # Event Map group
    grp_event = QGroupBox(
        "Event Map (Condition Label → Numerical ID)", container
    )
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

    # --- Start + Progress Row ---
    action_row = QHBoxLayout()
    action_row.setSpacing(16)

    # Create widgets
    self.btn_start = QPushButton(container)
    self.progress_bar = QProgressBar(container)

    # 1) Enlarge and fix the button size
    self.btn_start.setText("Start Processing")
    self.btn_start.setMinimumSize(150, 36)
    self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # 2) Center text in the progress bar and allow it to expand
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setFormat("%p%")
    self.progress_bar.setAlignment(Qt.AlignCenter)
    self.progress_bar.setFixedHeight(self.btn_start.sizeHint().height())
    self.progress_bar.setStyleSheet(
        """
        QProgressBar {
          min-height: 36px;
          text-align: center;
        }
        QProgressBar::chunk {
          background-color: #0BBF00;
        }
        """
    )

    # 3) Add with stretch so the bar fills leftover space
    action_row.addWidget(self.btn_start)
    action_row.addWidget(self.progress_bar, 1)

    main_layout.addLayout(action_row)
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

    # Finalize
    # Provide a reference for animations
    self.page1_container = container
    self.homeWidget = container
    self.stacked.addWidget(container)
    self.setStatusBar(QStatusBar(self))

    # Connect toolbar buttons to methods

    self.btn_add_row.clicked.connect(lambda: self.add_event_row())
    self.btn_detect.clicked.connect(self.detect_trigger_ids)

    # Sync the select button label with the current mode
    self._update_select_button_text()
