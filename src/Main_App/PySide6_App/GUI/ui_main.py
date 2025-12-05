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
    QButtonGroup,
    QScrollArea,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QPropertyAnimation
from PySide6.QtGui import QFont

from .menu_bar import build_menu_bar
from .header_bar import HeaderBar  # reusable header component


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
    # Row layout: [sidebar] | [header + content]  --> header aligns with sidebar top
    page1 = QWidget(self.stacked)
    page1.setObjectName("Page1")
    page1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    row = QHBoxLayout(page1)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)

    # Sidebar placeholder (populated by sidebar.init_sidebar)
    self.sidebar = QWidget(page1)
    self.sidebar.setObjectName("sidebar")
    self.sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    self.sidebar.setMinimumWidth(200)
    self.sidebar.setContentsMargins(0, 0, 0, 0)
    row.addWidget(self.sidebar)

    # Right: vertical stack -> header on top, content below
    right = QWidget(page1)
    right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    right_v = QVBoxLayout(right)
    right_v.setContentsMargins(0, 0, 0, 0)
    right_v.setSpacing(0)

    # Header bar at the very top (centered text)
    header = HeaderBar("Current Project: None", right)
    # Keep reference for external updates
    self.lbl_currentProject = header.titleLabel
    right_v.addWidget(header)

    # Content container under the header
    container = QWidget(right)
    container.setObjectName("MainContent")
    container.setAttribute(Qt.WA_StyledBackground, True)  # ensure background paints
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_layout = QVBoxLayout(container)
    # Consistent gutters and cushion under the header underline
    main_layout.setContentsMargins(16, 16, 16, 16)
    main_layout.setSpacing(12)
    right_v.addWidget(container, 1)

    # Add the right stack to the row
    row.addWidget(right, 1)

    # Gentle styling for the page (safe and minimal)
    page1.setStyleSheet("""
        /* Content background + cushion under header underline */
        #MainContent {
            background: #F8F8F8;
            padding-top: 8px;
        }

        /* Group boxes: NO negative top offset (prevents clipping) */
        QGroupBox {
            border: 1px solid #CFCFCF;
            border-radius: 8px;
            margin-top: 18px;              /* enough room for the title chip on all DPIs */
            background: #FFFFFF;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 6px;
            color: #333333;
            background: #F8F8F8;           /* mask the border behind the text */
            /* no 'top: -Npx' — avoids title being clipped */
        }

        /* Scroll area: remove gray seams around rounded inner panel */
        QScrollArea {
            background: transparent;
            border: none;
        }
        QScrollArea > QWidget > QWidget {
            background: transparent;
        }

        /* Inputs */
        QLineEdit, QComboBox, QProgressBar {
            border: 1px solid #C9C9C9;
            border-radius: 6px;
            padding: 6px;
            background: #FFFFFF;
        }

        /* Buttons: Windows-blue hover/press accents */
        QPushButton {
            border: 1px solid #C9C9C9;
            border-radius: 8px;
            padding: 8px 14px;
            background: #FFFFFF;
        }
        QPushButton:enabled:hover  { background: rgba(0,120,212,0.08); }  /* #0078D4 */
        QPushButton:enabled:pressed{ background: rgba(0,120,212,0.16); }
    """)

    # --- Content inside `container` ---
    # Processing Options
    grp_proc = QGroupBox("Processing Options", container)
    gl = QGridLayout(grp_proc)
    gl.addWidget(QLabel("Mode:"), 0, 0)
    self.rb_single = QRadioButton("Single File", grp_proc)
    self.rb_batch = QRadioButton("Batch Folder", grp_proc)
    gl.addWidget(self.rb_single, 0, 1)
    gl.addWidget(self.rb_batch, 0, 2)
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

    # --- Single-file selector row (hidden unless Single is active) ---
    self.row_single_file = QWidget(grp_proc)
    single_hl = QHBoxLayout(self.row_single_file)
    single_hl.setContentsMargins(0, 0, 0, 0)
    lbl_bdf = QLabel("EEG File (.bdf):", self.row_single_file)
    self.le_input_file = QLineEdit(self.row_single_file)
    self.le_input_file.setReadOnly(True)
    self.le_input_file.setPlaceholderText("Pick one .bdf for Single File mode…")
    self.btn_select_input_file = QPushButton("Browse…", self.row_single_file)
    single_hl.addWidget(lbl_bdf)
    single_hl.addWidget(self.le_input_file, 1)
    single_hl.addWidget(self.btn_select_input_file)
    # Place directly under the Mode row within Processing Options
    gl.addWidget(self.row_single_file, 1, 0, 1, 3)
    self.row_single_file.setVisible(False)  # default hidden; toggled by _on_mode_changed
    # Let main window decide when Start is enabled
    try:
        self.le_input_file.textChanged.connect(self._update_start_enabled)
    except Exception:
        pass
    main_layout.addWidget(grp_proc)

    # Load saved processing options
    mode = self.settings.get("processing", "mode", "batch").lower()
    (self.rb_batch if mode == "batch" else self.rb_single).setChecked(True)
    # Ensure initial Start-button state matches mode
    try:
        self._update_start_enabled()
    except Exception:
        pass


    # Preprocessing placeholder
    placeholder = QLabel("⚙️ Configure preprocessing in Settings", container)
    placeholder.setAlignment(Qt.AlignCenter)
    placeholder.setStyleSheet("color: #888888; font-style: italic;")
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

    # Optional: a tiny breather before the action row
    main_layout.addSpacing(4)

    # Start + Progress Row
    action_row = QHBoxLayout()
    action_row.setSpacing(16)

    self.btn_start = QPushButton(container)
    self.progress_bar = QProgressBar(container)

    self.btn_start.setText("Start Processing")
    self.btn_start.setMinimumSize(150, 36)
    self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # Progress bar setup (keep green chunk)
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setFormat("%p%")
    self.progress_bar.setAlignment(Qt.AlignCenter)

    # Lock both to the same height (matches across font DPI changes)
    btn_h = max(36, self.btn_start.sizeHint().height())
    self.btn_start.setFixedHeight(btn_h)
    self.progress_bar.setFixedHeight(btn_h)

    self.progress_bar.setStyleSheet(
        """
        QProgressBar { text-align: center; }
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

    # Finalize
    self.page1_container = container
    self.page1_right = container
    self.homeWidget = container

    self.stacked.addWidget(page1)

    # Wire buttons
    self.btn_add_row.clicked.connect(lambda: self.add_event_row())
    self.btn_detect.clicked.connect(self.detect_trigger_ids)

    # Sync select button label
    self._update_select_button_text()
