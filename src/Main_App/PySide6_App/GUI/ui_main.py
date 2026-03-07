# ui_main.py
"""UI initialization extracted from main_window.py."""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .header_bar import HeaderBar
from .menu_bar import build_menu_bar
from .style_tokens import (
    BROWSE_BUTTON_WIDTH,
    EVENT_ID_COLUMN_WIDTH,
    PAGE_MARGIN,
    SECTION_GAP,
    SECTION_PADDING,
    build_landing_page_stylesheet,
    build_main_page_stylesheet,
)


def init_ui(self) -> None:
    def add_card_header(parent: QWidget, title: str, object_name: str) -> QHBoxLayout:
        header = QWidget(parent)
        header.setObjectName(object_name)
        header.setProperty("cardHeader", True)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        title_label = QLabel(title, header)
        title_label.setProperty("cardTitle", True)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)

        return header_layout

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
    landing.setObjectName("LandingPage")
    landing.setAttribute(Qt.WA_StyledBackground, True)
    landing.setStyleSheet(build_landing_page_stylesheet())
    self.landing_page = landing

    lay0 = QVBoxLayout(landing)
    lay0.setContentsMargins(36, 32, 36, 28)
    lay0.setSpacing(0)

    landing_content = QWidget(landing)
    landing_content.setObjectName("landing_content")
    landing_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    self.landing_content = landing_content

    landing_layout = QVBoxLayout(landing_content)
    landing_layout.setContentsMargins(0, 0, 0, 0)
    landing_layout.setSpacing(0)
    landing_layout.addStretch(3)

    card_row = QHBoxLayout()
    card_row.setContentsMargins(0, 0, 0, 0)
    card_row.setSpacing(0)
    card_row.addStretch(1)

    welcome_card = QFrame(landing_content)
    welcome_card.setObjectName("landing_welcome_card")
    welcome_card.setAttribute(Qt.WA_StyledBackground, True)
    welcome_card.setMinimumWidth(560)
    welcome_card.setMaximumWidth(760)
    welcome_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.landing_card = welcome_card

    card_layout = QVBoxLayout(welcome_card)
    card_layout.setContentsMargins(28, 28, 28, 18)
    card_layout.setSpacing(18)

    card_header = QFrame(welcome_card)
    card_header.setObjectName("landing_card_header")
    card_header.setAttribute(Qt.WA_StyledBackground, True)
    header_layout = QVBoxLayout(card_header)
    header_layout.setContentsMargins(20, 18, 20, 18)
    header_layout.setSpacing(14)

    badge = QLabel("FPVS Toolbox", card_header)
    badge.setObjectName("landing_badge")
    badge.setAlignment(Qt.AlignCenter)
    badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    title = QLabel("Welcome to the FPVS Toolbox!", card_header)
    title.setObjectName("landing_title")
    title_font = QFont()
    title_font.setPointSize(26)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setWordWrap(True)

    subtitle = QLabel(
        "Create a new project or open an existing one to continue in the current workspace.",
        card_header,
    )
    subtitle.setObjectName("landing_subtitle")
    subtitle.setWordWrap(True)

    header_layout.addWidget(badge, 0, Qt.AlignLeft)
    header_layout.addWidget(title)
    header_layout.addWidget(subtitle)
    card_layout.addWidget(card_header)

    self.btn_create_project = QPushButton("Create New Project", welcome_card)
    self.btn_open_project = QPushButton("Open Existing Project", welcome_card)
    button_font = QFont()
    button_font.setPointSize(13)
    for btn in (self.btn_create_project, self.btn_open_project):
        btn.setProperty("landingAction", True)
        btn.setFont(button_font)
        btn.setFixedHeight(50)
        btn.setMinimumWidth(230)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(14)
    btn_row.addWidget(self.btn_create_project, 1)
    btn_row.addWidget(self.btn_open_project, 1)
    card_layout.addLayout(btn_row)

    footer = QFrame(welcome_card)
    footer.setObjectName("landing_footer")
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 10, 0, 0)
    footer_layout.setSpacing(8)

    self.landing_version_label = QLabel("", footer)
    self.landing_version_label.setObjectName("landing_version_label")
    footer_layout.addWidget(self.landing_version_label)
    footer_layout.addStretch(1)
    card_layout.addWidget(footer)

    card_row.addWidget(welcome_card)
    card_row.addStretch(1)
    landing_layout.addLayout(card_row)
    landing_layout.addStretch(2)
    lay0.addWidget(landing_content, 1)

    self.stacked.addWidget(landing)

    # ===== Page 1: Main UI =====
    page1 = QWidget(self.stacked)
    page1.setObjectName("Page1")
    page1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    page1.setStyleSheet(build_main_page_stylesheet())

    row = QHBoxLayout(page1)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)

    # Sidebar placeholder (populated by sidebar.init_sidebar)
    self.sidebar = QWidget(page1)
    self.sidebar.setObjectName("sidebar")
    self.sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    row.addWidget(self.sidebar)

    # Right: vertical stack -> header on top, content below
    right = QWidget(page1)
    right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    right_v = QVBoxLayout(right)
    right_v.setContentsMargins(0, 0, 0, 0)
    right_v.setSpacing(0)

    header = HeaderBar("Current Project: None", right)
    self.lbl_currentProject = header.titleLabel
    right_v.addWidget(header)

    container = QWidget(right)
    container.setObjectName("MainContent")
    container.setAttribute(Qt.WA_StyledBackground, True)
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_layout = QVBoxLayout(container)
    main_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    main_layout.setSpacing(0)
    right_v.addWidget(container, 1)

    row.addWidget(right, 1)

    splitter = QSplitter(Qt.Vertical, container)
    splitter.setObjectName("main_page_splitter")
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(8)
    main_layout.addWidget(splitter, 1)
    self.main_page_splitter = splitter

    setup_panel = QWidget(splitter)
    setup_panel.setObjectName("setup_panel")
    setup_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    setup_layout = QVBoxLayout(setup_panel)
    setup_layout.setContentsMargins(0, 0, 0, 0)
    setup_layout.setSpacing(SECTION_GAP)

    # Processing Options
    grp_proc = QGroupBox("", setup_panel)
    grp_proc.setObjectName("processing_group")
    proc_layout = QVBoxLayout(grp_proc)
    proc_layout.setContentsMargins(
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
    )
    proc_layout.setSpacing(10)

    proc_header_layout = add_card_header(
        grp_proc,
        "Processing Options",
        "processing_card_header",
    )
    proc_layout.addWidget(proc_header_layout.parentWidget())

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(8)
    form.setHorizontalSpacing(14)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)

    mode_field = QWidget(grp_proc)
    mode_field.setObjectName("mode_field")
    mode_layout = QHBoxLayout(mode_field)
    mode_layout.setContentsMargins(0, 0, 0, 0)
    mode_layout.setSpacing(14)

    self.rb_single = QRadioButton("Single File", grp_proc)
    self.rb_batch = QRadioButton("Batch Folder", grp_proc)
    mode_layout.addWidget(self.rb_single)
    mode_layout.addWidget(self.rb_batch)
    mode_layout.addStretch(1)

    form.addRow(QLabel("Mode", grp_proc), mode_field)

    self.lbl_single_file = QLabel("EEG File (.bdf)", grp_proc)
    self.row_single_file = QWidget(grp_proc)
    self.row_single_file.setObjectName("single_file_row")
    single_hl = QHBoxLayout(self.row_single_file)
    single_hl.setContentsMargins(0, 0, 0, 0)
    single_hl.setSpacing(10)

    self.le_input_file = QLineEdit(self.row_single_file)
    self.le_input_file.setReadOnly(True)
    self.le_input_file.setPlaceholderText("Select one .bdf file for single-file mode")

    self.btn_select_input_file = QPushButton("Select EEG File…", self.row_single_file)
    self.btn_select_input_file.setFixedWidth(BROWSE_BUTTON_WIDTH)
    self.btn_select_input_file.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    single_hl.addWidget(self.le_input_file, 1)
    single_hl.addWidget(self.btn_select_input_file, 0)

    form.addRow(self.lbl_single_file, self.row_single_file)

    self.lbl_input_folder = QLabel("Data Folder", grp_proc)
    self.row_input_folder = QWidget(grp_proc)
    self.row_input_folder.setObjectName("input_folder_row")
    folder_hl = QHBoxLayout(self.row_input_folder)
    folder_hl.setContentsMargins(0, 0, 0, 0)
    folder_hl.setSpacing(10)

    self.le_input_folder = QLineEdit(self.row_input_folder)
    self.le_input_folder.setReadOnly(True)
    self.le_input_folder.setPlaceholderText("Select the project data folder for batch mode")

    self.btn_select_input_folder = QPushButton("Select Data Folder...", self.row_input_folder)
    self.btn_select_input_folder.setFixedWidth(BROWSE_BUTTON_WIDTH)
    self.btn_select_input_folder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    folder_hl.addWidget(self.le_input_folder, 1)
    folder_hl.addWidget(self.btn_select_input_folder, 0)

    form.addRow(self.lbl_input_folder, self.row_input_folder)
    proc_layout.addLayout(form)

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

    info_strip = QFrame(grp_proc)
    info_strip.setObjectName("preprocessing_info_strip")
    info_layout = QHBoxLayout(info_strip)
    info_layout.setContentsMargins(10, 8, 10, 8)
    info_layout.setSpacing(8)

    info_icon = QLabel("i", info_strip)
    info_icon.setObjectName("preprocessing_info_icon")
    info_icon.setAlignment(Qt.AlignCenter)
    info_icon.setFixedSize(20, 20)

    info_text = QLabel(
        "Preprocessing options are configured in Settings.",
        info_strip,
    )
    info_text.setWordWrap(True)

    btn_open_settings = QPushButton("Open Settings", info_strip)
    btn_open_settings.setProperty("tertiary", True)
    btn_open_settings.setProperty("compact", True)
    btn_open_settings.clicked.connect(self.open_settings_window)

    info_layout.addWidget(info_icon, 0, Qt.AlignVCenter)
    info_layout.addWidget(info_text, 1)
    info_layout.addWidget(btn_open_settings, 0, Qt.AlignRight | Qt.AlignVCenter)
    proc_layout.addWidget(info_strip)

    setup_layout.addWidget(grp_proc)

    self.row_single_file.setVisible(False)
    self.lbl_single_file.setVisible(False)
    self.row_input_folder.setVisible(False)
    self.lbl_input_folder.setVisible(False)
    try:
        self.le_input_file.textChanged.connect(self._update_start_enabled)
    except Exception:
        pass

    mode = self.settings.get("processing", "mode", "batch").lower()
    (self.rb_batch if mode == "batch" else self.rb_single).setChecked(True)
    try:
        self._update_start_enabled()
    except Exception:
        pass

    # Event Map
    grp_event = QGroupBox("", setup_panel)
    grp_event.setObjectName("event_map_group")
    event_group_layout = QVBoxLayout(grp_event)
    event_group_layout.setContentsMargins(
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
    )
    event_group_layout.setSpacing(8)

    event_top_row = add_card_header(grp_event, "Event Map", "event_map_card_header")

    self.btn_detect = QPushButton("Detect Trigger IDs", grp_event)
    self.btn_detect.setProperty("secondary", True)
    self.btn_detect.setProperty("compact", True)
    self.btn_add_row = QPushButton("+ Add Condition", grp_event)
    self.btn_add_row.setProperty("secondary", True)
    self.btn_add_row.setProperty("compact", True)
    event_top_row.addWidget(self.btn_detect)
    event_top_row.addWidget(self.btn_add_row)
    event_group_layout.addWidget(event_top_row.parentWidget())

    event_header = QWidget(grp_event)
    event_header.setObjectName("event_map_header")
    header_layout = QHBoxLayout(event_header)
    header_layout.setContentsMargins(10, 0, 6, 0)
    header_layout.setSpacing(8)

    lbl_condition = QLabel("Condition", event_header)
    lbl_id = QLabel("Trigger ID", event_header)
    lbl_id.setFixedWidth(EVENT_ID_COLUMN_WIDTH)
    lbl_id.setAlignment(Qt.AlignCenter)
    lbl_actions = QLabel("", event_header)
    lbl_actions.setFixedWidth(24)

    header_layout.addWidget(lbl_condition, 1)
    header_layout.addWidget(lbl_id, 0)
    header_layout.addWidget(lbl_actions, 0)
    event_group_layout.addWidget(event_header)

    scroll = QScrollArea(grp_event)
    scroll.setObjectName("event_map_scroll")
    scroll.setWidgetResizable(True)

    self.event_container = QWidget()
    self.event_container.setObjectName("event_map_list")
    self.event_layout = QVBoxLayout(self.event_container)
    self.event_layout.setContentsMargins(0, 0, 0, 0)
    self.event_layout.setSpacing(6)
    scroll.setWidget(self.event_container)

    event_group_layout.addWidget(scroll, 1)
    setup_layout.addWidget(grp_event, 1)

    # Start + Progress Row
    run_panel = QWidget(setup_panel)
    run_panel.setObjectName("run_panel")
    action_row = QHBoxLayout(run_panel)
    action_row.setContentsMargins(0, 0, 0, 0)
    action_row.setSpacing(10)

    self.btn_start = QPushButton("Start Processing", run_panel)
    self.btn_start.setProperty("primary", True)
    self.btn_start.setMinimumSize(180, 38)
    self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    self.progress_bar = QProgressBar(run_panel)
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setFormat("%p%")
    self.progress_bar.setAlignment(Qt.AlignCenter)

    btn_h = max(38, self.btn_start.sizeHint().height())
    self.btn_start.setFixedHeight(btn_h)
    self.progress_bar.setFixedHeight(btn_h)

    action_row.addWidget(self.btn_start)
    action_row.addWidget(self.progress_bar, 1)
    setup_layout.addWidget(run_panel)

    self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
    self._progress_anim.setDuration(200)
    self._progress_anim.valueChanged.connect(self.progress_bar.setValue)
    self.processor.progressChanged.connect(self._animate_progress_to)

    saved_pairs = self.settings.get_event_pairs()
    if saved_pairs:
        for label, ident in saved_pairs:
            self.add_event_row(label, ident)
    else:
        self.add_event_row()

    # Log pane
    grp_log = QGroupBox("", splitter)
    grp_log.setObjectName("log_group")
    grp_log.setProperty("diagnosticsCard", True)
    lay_log = QVBoxLayout(grp_log)
    lay_log.setContentsMargins(
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
        SECTION_PADDING,
    )
    lay_log.setSpacing(10)

    log_header_layout = add_card_header(grp_log, "Log", "log_card_header")
    lay_log.addWidget(log_header_layout.parentWidget())

    self.text_log = QTextEdit(grp_log)
    self.text_log.setObjectName("log_surface")
    self.text_log.setReadOnly(True)
    self.text_log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
    lay_log.addWidget(self.text_log)

    splitter.addWidget(setup_panel)
    splitter.addWidget(grp_log)
    splitter.setStretchFactor(0, 5)
    splitter.setStretchFactor(1, 2)
    splitter.setSizes([620, 220])

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
