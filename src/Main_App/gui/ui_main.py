# ui_main.py
"""UI initialization extracted from main_window.py."""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.event_map import ConditionRowsArea, refresh_condition_editor_toggle
from Main_App.gui.icons import application_icon
from Main_App.gui.menu_bar import build_menu_bar
from Main_App.gui.processing_log_dialog import ProcessingLogDialog
from Main_App.gui.project_welcome import build_project_welcome
from Main_App.gui.processing_history_label import ProcessingHistoryLabel
from Main_App.gui.run_outcome import build_last_run_panel
from Main_App.gui.shell_status import PROCESSING_ACTIVITY_MESSAGE
from Main_App.gui.theme import set_themed_stylesheet
from .style_tokens import (
    BROWSE_BUTTON_WIDTH,
    EVENT_ID_COLUMN_WIDTH,
    EVENT_REMOVE_BUTTON_SIZE,
    PAGE_MARGIN,
    SECTION_GAP,
    build_main_page_stylesheet,
)
from Main_App.gui.components import (
    ActionRow,
    BusySpinner,
    SectionCard,
    SubsectionHeaderLabel,
    apply_font_role,
    make_action_button,
    make_form_layout,
)


def init_ui(self) -> None:
    self.setWindowIcon(application_icon())

    # Menu bar
    menu = build_menu_bar(self)
    self.setMenuBar(menu)

    # Keep the debug indicator in the menu row without reserving a toolbar row.
    self.lbl_debug = QLabel("DEBUG MODE ENABLED", menu)
    self.lbl_debug.setObjectName("workspaceDebugLabel")
    menu.setCornerWidget(self.lbl_debug, Qt.TopRightCorner)
    self.lbl_debug.setVisible(self.settings.debug_enabled())

    # Central stack
    self.stacked = QStackedWidget(self)
    # The shell owns the shared minimum. Stack hints include hidden pages.
    self.stacked.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
    self.setCentralWidget(self.stacked)

    self.landing_page = build_project_welcome(self, self.stacked)
    self.stacked.addWidget(self.landing_page)

    # ===== Page 1: Main UI =====
    page1 = QWidget(self.stacked)
    page1.setObjectName("Page1")
    page1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    shell_layout = QVBoxLayout(page1)
    shell_layout.setContentsMargins(0, 0, 0, 0)
    shell_layout.setSpacing(0)

    container = QWidget(page1)
    container.setObjectName("MainContent")
    container.setAutoFillBackground(True)
    container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_layout = QVBoxLayout(container)
    main_layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    main_layout.setSpacing(0)
    shell_layout.addWidget(container, 1)

    self.workspace_stack = QStackedWidget(container)
    self.workspace_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
    self.workspace_stack.setObjectName("workspace_stack")
    main_layout.addWidget(self.workspace_stack, 1)

    setup_panel = QWidget(self.workspace_stack)
    setup_panel.setObjectName("setup_panel")
    set_themed_stylesheet(setup_panel, build_main_page_stylesheet())
    setup_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    setup_layout = QVBoxLayout(setup_panel)
    setup_layout.setContentsMargins(0, 0, 0, 0)
    setup_layout.setSpacing(SECTION_GAP)

    overview = QHBoxLayout()
    overview.setSpacing(SECTION_GAP)
    setup_layout.addLayout(overview)
    processing_column = QVBoxLayout()
    processing_column.setSpacing(SECTION_GAP)
    overview.addLayout(processing_column, 3)

    grp_proc = SectionCard("Process recordings", setup_panel, object_name="processing_group")
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

    form.addRow(mode_field)

    self.lbl_single_file = QLabel("EEG recording", grp_proc)
    self.row_single_file = QWidget(grp_proc)
    self.row_single_file.setObjectName("single_file_row")
    single_hl = QHBoxLayout(self.row_single_file)
    single_hl.setContentsMargins(0, 0, 0, 0)
    single_hl.setSpacing(10)

    self.le_input_file = QLineEdit(self.row_single_file)
    self.le_input_file.setReadOnly(True)
    self.le_input_file.setPlaceholderText("No recording selected")

    self.btn_select_input_file = make_action_button(
        "Browse…",
        parent=self.row_single_file,
    )
    self.btn_select_input_file.setFixedWidth(BROWSE_BUTTON_WIDTH)
    self.btn_select_input_file.setAccessibleName("Choose EEG recording")
    self.btn_select_input_file.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    single_hl.addWidget(self.le_input_file, 1)
    single_hl.addWidget(self.btn_select_input_file, 0)

    form.addRow(self.lbl_single_file, self.row_single_file)
    self.lbl_single_file.setBuddy(self.le_input_file)

    self.lbl_input_folder = QLabel("EEG folder", grp_proc)
    self.row_input_folder = QWidget(grp_proc)
    self.row_input_folder.setObjectName("input_folder_row")
    folder_hl = QHBoxLayout(self.row_input_folder)
    folder_hl.setContentsMargins(0, 0, 0, 0)
    folder_hl.setSpacing(10)

    self.le_input_folder = QLineEdit(self.row_input_folder)
    self.le_input_folder.setReadOnly(True)
    self.le_input_folder.setPlaceholderText("No folder selected")

    self.btn_select_input_folder = make_action_button(
        "Browse…",
        parent=self.row_input_folder,
    )
    self.btn_select_input_folder.setFixedWidth(BROWSE_BUTTON_WIDTH)
    self.btn_select_input_folder.setAccessibleName("Choose EEG folder")
    self.btn_select_input_folder.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    folder_hl.addWidget(self.le_input_folder, 1)
    folder_hl.addWidget(self.btn_select_input_folder, 0)

    form.addRow(self.lbl_input_folder, self.row_input_folder)
    self.lbl_input_folder.setBuddy(self.le_input_folder)
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

    processing_column.addWidget(grp_proc)

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

    self.processing_readiness_label = QLabel(grp_proc)
    self.processing_readiness_label.setObjectName("processing_readiness_label")
    self.processing_readiness_label.setWordWrap(True)
    self.processing_readiness_label.hide()
    proc_layout.addWidget(self.processing_readiness_label)

    # Start Row
    run_panel = ActionRow(grp_proc, alignment=Qt.AlignRight, spacing=10)
    run_panel.setObjectName("run_panel")
    self.run_panel = run_panel
    self.project_draft_status = QLabel(run_panel)
    self.project_draft_status.setObjectName("project_draft_status")
    self.project_draft_status.setAccessibleName("Project save status")
    run_panel.row_layout.insertWidget(0, self.project_draft_status)

    self.processing_log_dialog = ProcessingLogDialog(self)
    self.text_log = self.processing_log_dialog.viewer
    self.btn_view_log = make_action_button(
        "View Log",
        variant="secondary",
        parent=run_panel,
    )
    self.btn_view_log.setObjectName("processing_view_log_button")
    self.btn_view_log.setAccessibleName("View processing log")
    self.btn_view_log.clicked.connect(self.processing_log_dialog.open)

    self.btn_start = make_action_button(
        "Start Processing",
        variant="primary",
        parent=run_panel,
    )
    self.btn_start.setMinimumSize(180, 38)
    self.btn_start.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    btn_h = max(38, self.btn_start.sizeHint().height())
    self.btn_start.setFixedHeight(btn_h)

    run_panel.add_button(self.btn_view_log)
    run_panel.add_button(self.btn_start)
    proc_layout.addWidget(run_panel)


    # Conditions
    grp_event = SectionCard("Conditions", setup_panel, object_name="event_map_group")
    grp_event.header.setObjectName("event_map_card_header")
    self.condition_summary_label = QLabel("None configured", grp_event.header)
    self.condition_summary_label.setObjectName("home_condition_summary")
    self.condition_summary_label.setTextFormat(Qt.PlainText)
    grp_event.header.header_layout.insertWidget(1, self.condition_summary_label)

    self.condition_editor_toggle = make_action_button("Edit conditions", compact=True, parent=grp_event)
    self.condition_editor_toggle.setObjectName("home_condition_editor_toggle")
    self.condition_editor_toggle.setCheckable(True)
    self.condition_editor_toggle.setAccessibleDescription("Show or hide condition rows and source controls.")
    grp_event.header.add_action_widget(self.condition_editor_toggle)

    self.condition_editor_body = grp_event.content
    self.condition_editor_body.setObjectName("home_condition_editor")
    event_group_layout = grp_event.content_layout

    self.btn_add_row = make_action_button(
        "+ Add Condition",
        compact=True,
        parent=grp_event,
    )
    self.trigger_maps_button = make_action_button("Use source maps…", compact=True, parent=grp_event)
    self.trigger_maps_button.setObjectName("home_trigger_maps")
    from Main_App.gui.trigger_maps_workflow import show_home_trigger_maps, show_source_participants
    self.trigger_maps_button.clicked.connect(lambda: show_home_trigger_maps(self))
    self.source_participants_button = make_action_button("Source participants…", compact=True, parent=grp_event)
    self.source_participants_button.setObjectName("home_source_participants")
    self.source_participants_button.clicked.connect(lambda: show_source_participants(self))
    condition_actions = ActionRow(grp_event.content, alignment=Qt.AlignLeft)
    condition_actions.setObjectName("home_condition_actions")
    condition_actions.add_button(self.trigger_maps_button)
    condition_actions.add_button(self.source_participants_button)
    condition_actions.row_layout.addStretch(1)
    condition_actions.add_button(self.btn_add_row)
    event_group_layout.addWidget(condition_actions)

    event_header = QWidget(grp_event)
    event_header.setObjectName("event_map_header")
    header_layout = QHBoxLayout(event_header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    lbl_condition = SubsectionHeaderLabel("Condition", event_header)
    lbl_id = SubsectionHeaderLabel("Trigger ID", event_header, alignment=Qt.AlignCenter)
    lbl_id.setFixedWidth(EVENT_ID_COLUMN_WIDTH)
    lbl_actions = QLabel("", event_header)
    self.event_id_header = lbl_id
    self.event_actions_header = lbl_actions
    lbl_actions.setFixedWidth(EVENT_REMOVE_BUTTON_SIZE)

    header_layout.addWidget(lbl_condition, 1)
    header_layout.addWidget(lbl_id, 0)
    header_layout.addWidget(lbl_actions, 0)
    event_group_layout.addWidget(event_header)

    scroll = ConditionRowsArea(grp_event)
    scroll.setObjectName("event_map_scroll")
    scroll.setWidgetResizable(True)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    scrollbar = scroll.verticalScrollBar()
    scrollbar.rangeChanged.connect(
        lambda minimum, maximum: header_layout.setContentsMargins(
            0, 0, scrollbar.sizeHint().width() if maximum > minimum else 0, 0,
        ),
    )

    self.event_container = QWidget()
    self.event_container.setObjectName("event_map_list")
    self.event_layout = QVBoxLayout(self.event_container)
    self.event_layout.setContentsMargins(0, 0, 0, 0)
    self.event_layout.setSpacing(4)
    self.event_layout.setAlignment(Qt.AlignTop)
    scroll.setWidget(self.event_container)

    event_group_layout.addWidget(scroll, 1)
    grp_event.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    self.condition_editor_body.hide()
    self.condition_editor_toggle.toggled.connect(self.condition_editor_body.setVisible)
    self.condition_editor_toggle.toggled.connect(lambda _checked: refresh_condition_editor_toggle(self))
    processing_column.addWidget(grp_event)
    processing_column.addStretch(1)

    results = SectionCard("Analysis", setup_panel, object_name="home_analysis")
    self.processing_history_label = ProcessingHistoryLabel(results)
    results.content_layout.addWidget(self.processing_history_label)
    self.last_run_panel = build_last_run_panel(self, results)
    results.content_layout.addWidget(self.last_run_panel)
    tool_row = ActionRow(results, alignment=Qt.AlignLeft)
    for role in ("btn_graphs", "btn_publication_maps", "btn_loreta_visualizer"):
        action = self.tool_actions.get(role)
        if action is not None:
            button = make_action_button(action.text(), compact=True, parent=tool_row)
            button.setObjectName(f"home_{role}")
            # QAction.trigger() can run even when its menu widget is locked.
            button.clicked.connect(
                lambda _checked, tool=action: tool.trigger() if menu.isEnabled() else None,
            )
            tool_row.add_button(button)
    tool_row.row_layout.addStretch(1)
    results.content_layout.addWidget(tool_row)
    overview.addWidget(results, 2, Qt.AlignTop)

    self.condition_editor_toggle.toggled.connect(lambda opened: results.setVisible(not opened))
    setup_layout.addStretch(1)

    saved_pairs = self.settings.get_event_pairs()
    if saved_pairs:
        for label, ident in saved_pairs:
            self.add_event_row(label, ident)
    else:
        self.add_event_row()

    # Finalize
    self.workspace_stack.addWidget(setup_panel)
    self.page1_container = container
    self.homeWidget = setup_panel

    processing_page = QWidget(self.workspace_stack)
    processing_page.setObjectName("processing_page")
    set_themed_stylesheet(processing_page, build_main_page_stylesheet())
    processing_page.setAttribute(Qt.WA_StyledBackground, True)
    processing_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    self.processing_page = processing_page

    processing_layout = QVBoxLayout(processing_page)
    processing_layout.setContentsMargins(0, 0, 0, 0)
    processing_layout.setSpacing(SECTION_GAP)

    processing_header = QWidget(processing_page)
    processing_header.setObjectName("processing_activity_header")
    processing_header.setAttribute(Qt.WA_StyledBackground, True)
    processing_header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    processing_header_layout = QHBoxLayout(processing_header)
    processing_header_layout.setContentsMargins(0, 0, 0, 0)
    processing_header_layout.setSpacing(12)

    self.processing_spinner = BusySpinner(processing_header, diameter=40)
    self.processing_spinner.setObjectName("processing_spinner")
    processing_header_layout.addWidget(self.processing_spinner, 0, Qt.AlignVCenter)

    processing_intro = QWidget(processing_header)
    processing_intro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    processing_intro_layout = QVBoxLayout(processing_intro)
    processing_intro_layout.setContentsMargins(0, 0, 0, 0)
    processing_intro_layout.setSpacing(4)

    self.processing_title_label = QLabel("Processing Data", processing_intro)
    self.processing_title_label.setObjectName("processing_title")
    apply_font_role(self.processing_title_label, "project_title")
    self.processing_title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    processing_intro_layout.addWidget(self.processing_title_label)

    self.processing_step_label = QLabel("", processing_intro)
    self.processing_step_label.setObjectName("processing_step_label")
    apply_font_role(self.processing_step_label, "caption")
    self.processing_step_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    self.processing_step_label.setVisible(False)
    processing_intro_layout.addWidget(self.processing_step_label)

    self.processing_message_label = QLabel(
        PROCESSING_ACTIVITY_MESSAGE,
        processing_intro,
    )
    self.processing_message_label.setObjectName("processing_message")
    apply_font_role(self.processing_message_label, "body")
    self.processing_message_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    self.processing_message_label.setWordWrap(True)
    processing_intro_layout.addWidget(self.processing_message_label)

    processing_header_layout.addWidget(processing_intro, 1)

    self.processing_action_slot = QWidget(processing_header)
    self.processing_action_slot.setObjectName("processing_action_slot")
    self.processing_action_slot.setVisible(False)
    self.processing_action_slot.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    self.processing_action_layout = QVBoxLayout(self.processing_action_slot)
    self.processing_action_layout.setContentsMargins(0, 0, 0, 0)
    self.processing_action_layout.setSpacing(8)
    self.processing_action_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    processing_header_layout.addWidget(
        self.processing_action_slot,
        0,
        Qt.AlignRight | Qt.AlignVCenter,
    )
    processing_layout.addWidget(processing_header)

    # These compatibility-named containers intentionally remain plain widgets.
    # The activity page is already the section boundary, so framing its children
    # would create a card-within-card hierarchy during processing and QC review.
    self.processing_status_card = QWidget(processing_page)
    self.processing_status_card.setObjectName("processing_status_card")
    processing_status_layout = QVBoxLayout(self.processing_status_card)
    processing_status_layout.setContentsMargins(0, 0, 0, 0)
    processing_status_layout.setSpacing(8)

    self.processing_status_title_label = SubsectionHeaderLabel(
        "Run Progress",
        self.processing_status_card,
    )
    self.processing_status_title_label.setObjectName("processing_status_title")
    processing_status_layout.addWidget(self.processing_status_title_label)

    self.processing_overview_row = QWidget(self.processing_status_card)
    self.processing_overview_row.setObjectName("processing_overview_row")
    processing_overview_layout = QHBoxLayout(self.processing_overview_row)
    processing_overview_layout.setContentsMargins(0, 0, 0, 0)
    processing_overview_layout.setSpacing(SECTION_GAP * 2)

    self.processing_instruction_panel = QWidget(self.processing_overview_row)
    processing_instruction_layout = QVBoxLayout(self.processing_instruction_panel)
    processing_instruction_layout.setContentsMargins(0, 0, 0, 0)
    processing_instruction_layout.setSpacing(8)

    self.processing_summary_heading_label = SubsectionHeaderLabel(
        "Run Status",
        self.processing_instruction_panel,
    )
    self.processing_summary_heading_label.setObjectName("processing_summary_heading")
    processing_instruction_layout.addWidget(self.processing_summary_heading_label)

    self.processing_summary_label = QLabel(
        "Waiting for files...",
        self.processing_instruction_panel,
    )
    self.processing_summary_label.setObjectName("processing_summary_label")
    self.processing_summary_label.setWordWrap(True)
    apply_font_role(self.processing_summary_label, "body")
    processing_instruction_layout.addWidget(self.processing_summary_label)
    processing_instruction_layout.addStretch(1)
    processing_overview_layout.addWidget(self.processing_instruction_panel, 3)

    self.processing_checklist_panel = QWidget(self.processing_overview_row)
    self.processing_checklist_panel.hide()
    processing_checklist_layout = QVBoxLayout(self.processing_checklist_panel)
    processing_checklist_layout.setContentsMargins(0, 0, 0, 0)
    processing_checklist_layout.setSpacing(8)

    self.processing_checklist_heading_label = SubsectionHeaderLabel(
        "Checks In This Step",
        self.processing_checklist_panel,
    )
    self.processing_checklist_heading_label.setObjectName("processing_checklist_heading")
    processing_checklist_layout.addWidget(self.processing_checklist_heading_label)

    self.processing_checklist_label = QLabel("", self.processing_checklist_panel)
    self.processing_checklist_label.setObjectName("processing_checklist_label")
    self.processing_checklist_label.setWordWrap(True)
    apply_font_role(self.processing_checklist_label, "body")
    processing_checklist_layout.addWidget(self.processing_checklist_label)
    processing_checklist_layout.addStretch(1)
    processing_overview_layout.addWidget(self.processing_checklist_panel, 2)
    processing_status_layout.addWidget(self.processing_overview_row)

    self.processing_status_separator = QFrame(self.processing_status_card)
    self.processing_status_separator.setObjectName("processing_status_separator")
    self.processing_status_separator.setFrameShape(QFrame.HLine)
    self.processing_status_separator.setFrameShadow(QFrame.Plain)
    processing_status_layout.addWidget(self.processing_status_separator)

    self.processing_live_heading_label = SubsectionHeaderLabel(
        "Live Status",
        self.processing_status_card,
    )
    self.processing_live_heading_label.setObjectName("processing_live_heading")
    processing_status_layout.addWidget(self.processing_live_heading_label)

    self.processing_current_file_label = QLabel(
        "Latest file: Not started",
        self.processing_status_card,
    )
    self.processing_current_file_label.setObjectName("processing_current_file_label")
    self.processing_current_file_label.setWordWrap(True)
    processing_status_layout.addWidget(self.processing_current_file_label)

    self.processing_progress_heading_label = SubsectionHeaderLabel(
        "Progress",
        self.processing_status_card,
    )
    self.processing_progress_heading_label.setObjectName("processing_progress_heading")
    self.processing_progress_heading_label.hide()
    processing_status_layout.insertWidget(1, self.processing_progress_heading_label)

    self.progress_bar = QProgressBar(self.processing_status_card)
    self.progress_bar.setObjectName("processing_progress_bar")
    self.progress_bar.setRange(0, 100)
    self.progress_bar.setValue(0)
    self.progress_bar.setTextVisible(True)
    self.progress_bar.setFormat("%p%")
    self.progress_bar.setAlignment(Qt.AlignCenter)
    self.progress_bar.setFixedHeight(btn_h)
    processing_status_layout.insertWidget(2, self.progress_bar)
    processing_status_layout.addStretch(1)
    processing_layout.addWidget(self.processing_status_card)

    self.processing_files_card = QWidget(processing_page)
    self.processing_files_card.setObjectName("processing_files_card")
    processing_files_layout = QVBoxLayout(self.processing_files_card)
    processing_files_layout.setContentsMargins(0, 0, 0, 0)
    processing_files_layout.setSpacing(SECTION_GAP)

    self.processing_files_title_label = SubsectionHeaderLabel(
        "File Completion",
        self.processing_files_card,
    )
    self.processing_files_title_label.setObjectName("processing_files_title")
    processing_files_layout.addWidget(self.processing_files_title_label)

    self.processing_files_table = QTableWidget(0, 2, self.processing_files_card)
    self.processing_files_table.setObjectName("processing_files_table")
    self.processing_files_table.setHorizontalHeaderLabels(["Status", "File"])
    self.processing_files_table.verticalHeader().hide()
    self.processing_files_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    self.processing_files_table.setSelectionMode(QAbstractItemView.NoSelection)
    self.processing_files_table.setFocusPolicy(Qt.NoFocus)
    self.processing_files_table.setAlternatingRowColors(True)
    self.processing_files_table.horizontalHeader().setStretchLastSection(True)
    self.processing_files_table.horizontalHeader().setSectionResizeMode(
        0,
        QHeaderView.ResizeToContents,
    )
    self.processing_files_table.horizontalHeader().setSectionResizeMode(
        1,
        QHeaderView.Stretch,
    )
    processing_files_layout.addWidget(self.processing_files_table, 1)
    processing_layout.addWidget(self.processing_files_card, 1)
    self.workspace_stack.addWidget(processing_page)

    self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
    self._progress_anim.setDuration(200)
    self._progress_anim.valueChanged.connect(self.progress_bar.setValue)
    self.processor.progressChanged.connect(self._animate_progress_to)
    self.stacked.addWidget(page1)

    # Wire buttons
    self.btn_add_row.clicked.connect(lambda: self.add_event_row())

    # Sync select button label
    self._update_select_button_text()
