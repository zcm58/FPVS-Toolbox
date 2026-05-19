# ui_main.py
"""UI initialization extracted from main_window.py."""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
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

from Main_App.gui.header_bar import HeaderBar
from Main_App.gui.menu_bar import build_menu_bar
from .style_tokens import (
    BROWSE_BUTTON_WIDTH,
    EVENT_ID_COLUMN_WIDTH,
    PAGE_MARGIN,
    SECTION_GAP,
    build_landing_page_stylesheet,
    build_main_page_stylesheet,
)
from Main_App.gui.components import (
    ActionRow,
    SectionCard,
    SubsectionHeaderLabel,
    make_action_button,
    make_form_layout,
)


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
    landing.setObjectName("LandingPage")
    landing.setAttribute(Qt.WA_StyledBackground, True)
    landing.setStyleSheet(build_landing_page_stylesheet())
    self.landing_page = landing

    lay0 = QVBoxLayout(landing)
    lay0.setContentsMargins(26, 26, 26, 24)
    lay0.setSpacing(0)

    landing_content = QWidget(landing)
    landing_content.setObjectName("landing_content")
    landing_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    self.landing_content = landing_content

    landing_layout = QVBoxLayout(landing_content)
    landing_layout.setContentsMargins(0, 0, 0, 0)
    landing_layout.setSpacing(0)

    welcome_card = QFrame(landing_content)
    welcome_card.setObjectName("landing_welcome_card")
    welcome_card.setAttribute(Qt.WA_StyledBackground, True)
    welcome_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    self.landing_card = welcome_card

    card_layout = QVBoxLayout(welcome_card)
    card_layout.setContentsMargins(32, 32, 32, 32)
    card_layout.setSpacing(0)
    card_layout.addStretch(1)

    center_content = QWidget(welcome_card)
    center_content.setObjectName("landing_center_content")
    center_content.setMinimumWidth(620)
    center_content.setMaximumWidth(760)
    center_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    center_layout = QVBoxLayout(center_content)
    center_layout.setContentsMargins(0, 0, 0, 0)
    center_layout.setSpacing(18)

    badge = QLabel("FPVS Toolbox", center_content)
    badge.setObjectName("landing_badge")
    badge.setAlignment(Qt.AlignCenter)

    title = QLabel("Welcome to FPVS Toolbox!", center_content)
    title.setObjectName("landing_title")
    title_font = QFont()
    title_font.setPointSize(28)
    title_font.setBold(True)
    title.setFont(title_font)
    title.setAlignment(Qt.AlignCenter)
    title.setWordWrap(False)
    title.setMinimumHeight(58)
    title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    subtitle = QLabel(
        "Create a new FPVS project or open an existing one.",
        center_content,
    )
    subtitle.setObjectName("landing_subtitle")
    subtitle.setAlignment(Qt.AlignCenter)
    subtitle.setWordWrap(True)

    center_layout.addWidget(badge)
    center_layout.addWidget(title)
    center_layout.addWidget(subtitle)

    self.btn_create_project = make_action_button(
        "New Project",
        variant="primary",
        parent=welcome_card,
    )
    self.btn_open_project = make_action_button(
        "Open Project",
        variant="secondary",
        parent=welcome_card,
    )
    button_font = QFont()
    button_font.setPointSize(11)
    for btn in (self.btn_create_project, self.btn_open_project):
        btn.setProperty("landingAction", True)
        btn.setFont(button_font)
        btn.setFixedSize(220, 52)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    btn_row = ActionRow(welcome_card, alignment=Qt.AlignRight, spacing=12)
    btn_row.setObjectName("main_landing_actions")
    btn_row.add_button(self.btn_create_project)
    btn_row.add_button(self.btn_open_project)
    btn_row.row_layout.addStretch(1)
    center_layout.addWidget(btn_row)

    self.landing_version_label = QLabel("", welcome_card)
    self.landing_version_label.setObjectName("landing_version_label")
    self.landing_version_label.setVisible(False)

    card_layout.addWidget(center_content, 0, Qt.AlignCenter)
    card_layout.addStretch(1)
    landing_layout.addWidget(welcome_card)
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

    self.workspace_stack = QStackedWidget(container)
    self.workspace_stack.setObjectName("workspace_stack")
    main_layout.addWidget(self.workspace_stack, 1)

    splitter = QSplitter(Qt.Vertical, self.workspace_stack)
    splitter.setObjectName("main_page_splitter")
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(8)
    self.main_page_splitter = splitter

    setup_panel = QWidget(splitter)
    setup_panel.setObjectName("setup_panel")
    setup_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    setup_layout = QVBoxLayout(setup_panel)
    setup_layout.setContentsMargins(0, 0, 0, 0)
    setup_layout.setSpacing(SECTION_GAP)

    # Processing Options
    grp_proc = SectionCard("Processing Options", setup_panel, object_name="processing_group")
    grp_proc.header.setObjectName("processing_card_header")
    proc_layout = grp_proc.content_layout
    proc_layout.setSpacing(10)

    form = make_form_layout()

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

    self.btn_select_input_file = make_action_button(
        "Select EEG File...",
        parent=self.row_single_file,
    )
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

    self.btn_select_input_folder = make_action_button(
        "Select Data Folder...",
        parent=self.row_input_folder,
    )
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
    grp_event = SectionCard("Event Map", setup_panel, object_name="event_map_group")
    grp_event.header.setObjectName("event_map_card_header")
    grp_event.header.title_label.setText("")
    grp_event.header.hide()
    event_group_layout = grp_event.content_layout
    event_group_layout.setSpacing(8)

    self.btn_add_row = make_action_button(
        "+ Add Condition",
        compact=True,
        parent=grp_event,
    )

    event_header = QWidget(grp_event)
    event_header.setObjectName("event_map_header")
    header_layout = QHBoxLayout(event_header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    lbl_condition = SubsectionHeaderLabel("Condition", event_header)
    lbl_id = SubsectionHeaderLabel("Trigger ID", event_header, alignment=Qt.AlignCenter)
    lbl_id.setFixedWidth(EVENT_ID_COLUMN_WIDTH)
    lbl_actions = QLabel("", event_header)
    lbl_actions.setFixedWidth(24)

    header_layout.addWidget(lbl_condition, 1)
    header_layout.addWidget(lbl_id, 0)
    header_layout.addWidget(self.btn_add_row, 0)
    header_layout.addWidget(lbl_actions, 0)
    event_group_layout.addWidget(event_header)

    scroll = QScrollArea(grp_event)
    scroll.setObjectName("event_map_scroll")
    scroll.setWidgetResizable(True)

    self.event_container = QWidget()
    self.event_container.setObjectName("event_map_list")
    self.event_layout = QVBoxLayout(self.event_container)
    self.event_layout.setContentsMargins(0, 0, 0, 0)
    self.event_layout.setSpacing(4)
    scroll.setWidget(self.event_container)

    event_group_layout.addWidget(scroll, 1)
    setup_layout.addWidget(grp_event, 1)

    # Start + Progress Row
    run_panel = ActionRow(setup_panel, alignment=Qt.AlignLeft, spacing=10)
    run_panel.setObjectName("run_panel")

    self.btn_start = make_action_button(
        "Start Processing",
        variant="primary",
        parent=run_panel,
    )
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

    run_panel.add_button(self.btn_start)
    run_panel.row_layout.addWidget(self.progress_bar, 1)
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
    grp_log = SectionCard("Log", splitter, object_name="log_group")
    grp_log.setProperty("diagnosticsCard", True)
    grp_log.header.setObjectName("log_card_header")
    lay_log = grp_log.content_layout
    lay_log.setSpacing(10)

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
    self.workspace_stack.addWidget(splitter)
    self.page1_container = container
    self.page1_right = container
    self.homeWidget = splitter
    self.stacked.addWidget(page1)

    # Wire buttons
    self.btn_add_row.clicked.connect(lambda: self.add_event_row())

    # Sync select button label
    self._update_select_button_text()
