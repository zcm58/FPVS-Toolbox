"""Harmonic selection controls and method help for Settings.

Builders populate the existing SettingsDialog and connect its workflow methods.
The dialog retains draft validation, persistence, and background-work ownership.
"""

from __future__ import annotations

from typing import Any, Dict
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QTabWidget,
    QCheckBox,
)
from Main_App.gui.components import (
    ActionRow,
    SectionCard,
    StatusBanner,
    ToolInfoContent,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.components import make_info_button
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
    FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
    FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    HARMONIC_PROFILE_FIXED_ID,
    HARMONIC_PROFILE_LEGACY_ID,
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    normalize_dv_policy,
)


# Primary-source method checks are recorded under "Harmonic method references"
# in docs/user/reference/methods-reporting-checklist.md. This catalog is presentation
# only and does not change the versioned profile registry.
HARMONIC_METHOD_INFO = {
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID: ToolInfoContent(
        key="harmonic_method_two_failures",
        title="Stop after two consecutive failures",
        html="""
        <p>Checks harmonics in order and stops when two eligible harmonics in a
        row are not detected above noise (z &le; 1.64). It sums the eligible
        range before that pair, including any earlier single gaps. Frequencies
        overlapping the base rate are skipped.</p>
        <p>The Toolbox gives groups and conditions equal weight and uses one
        list for everyone. Its group balancing extends the published rule.
        Selection uses the analyzed data, so findings remain exploratory.</p>
        <p><b>Recent uses of the stopping rule</b><br>
        These papers use the same stopping idea; their averaging, thresholds
        and experimental designs can differ.</p>
        <ul>
        <li><a href="https://doi.org/10.1162/jocn.a.94">Bourgaux et al. (2026)
        — Context matters: human faces hinder face pareidolia</a>.
        Pools channels, contexts and participants before testing.</li>
        <li><a href="https://doi.org/10.1186/s13229-025-00672-2">Van den Broeck
        et al. (2025) — Social orienting in prematurely born preschoolers</a>.
        Uses selected scalp electrodes and competing stimulation streams.</li>
        <li><a href="https://doi.org/10.1016/j.cub.2023.11.042">Calce et al.
        (2024) — Voice categorization in the four-month-old human brain</a>.
        Auditory frequency tagging; uses the largest cutoff across conditions.</li>
        <li><a href="https://doi.org/10.3390/brainsci12091224">Qiao et al.
        (2022) — Oxytocin and competing social and non-social visual streams</a>.
        Applies the rule to responses from superimposed visual streams.</li>
        <li><a href="https://doi.org/10.3389/fnins.2022.901013">Poncet et al.
        (2022) — Facial-expression discrimination in young infants</a>.
        Uses z &gt; 1.96 within channels and age groups.</li>
        </ul>
        <p><b>Foundational papers</b></p>
        <ul>
        <li><a href="https://doi.org/10.1016/j.neuropsychologia.2019.03.006">Poncet
        et al. (2019) — Rapid and automatic discrimination between facial
        expressions in the human brain</a>. Pools conditions before testing.</li>
        <li><a href="https://doi.org/10.1093/cercor/bhw223">Dzhelyova et al.
        (2017) — Brief changes of facial expression</a>. Averages condition
        Z-scores to choose the stopping point.</li>
        </ul>
        <p>References checked October 2026, focusing on 2020 onward plus
        foundational papers.</p>
        """,
    ),
    HARMONIC_PROFILE_FIXED_ID: ToolInfoContent(
        key="harmonic_method_fixed",
        title="Fixed / preregistered harmonic domain",
        html="""
        <p>Uses the frequencies you specify, without selecting them from this
        dataset's responses. Enter an exact list, a highest harmonic number,
        or an upper frequency. Frequencies overlapping the base rate are
        always removed.</p>
        <p>Choose the list from prior work or an analysis plan before inspecting
        these data. Selecting this option does not itself make a study
        preregistered.</p>
        <p><b>Publications using a fixed domain</b><br>
        These examples use fixed selections; they do not all claim
        preregistration, and their response measures differ.</p>
        <ul>
        <li><a href="https://doi.org/10.1162/imag_a_00414">Hauk et al. (2025)
        — Word-selective EEG/MEG responses in English</a>.
        Uses ten word-response harmonics instead of testing each one for
        inclusion.</li>
        <li><a href="https://doi.org/10.3389/fpsyg.2022.932952">Pescuma et al.
        (2022) — Automatic morpheme identification across development</a>.
        Averages SNR at 1.2, 2.4, 3.6 and 4.8 Hz.</li>
        <li><a href="https://doi.org/10.1016/j.cortex.2022.01.005">De Rosa et al.
        (2022) — Frequency-based neural discrimination</a>.
        Sums baseline-corrected responses at 1.2, 2.4, 3.6 and 4.8 Hz.</li>
        <li><a href="https://doi.org/10.1016/j.neuroimage.2021.118460">Hauk
        et al. (2021) — Face-selective responses in combined EEG/MEG</a>.
        Uses a fixed face-response range through 14.4 Hz, excluding base
        overlaps.</li>
        </ul>
        <p><b>Earlier precedent</b></p>
        <ul>
        <li><a href="https://doi.org/10.1016/j.visres.2018.02.009">Retter et al.
        (2018) — Presentation timing and rapid face categorization</a>.
        Sets the face-response range from prior work, rather than the current
        sample's significance cutoff.</li>
        <li><a href="https://doi.org/10.1016/j.neuroimage.2018.06.048">Leleu
        et al. (2018) — Tuning to brief changes of facial expression</a>.
        Uses an oddball range through harmonic 14 from prior research; its
        separate base-response analysis uses the two-failure rule.</li>
        </ul>
        <p>References checked October 2026, focusing on 2020 onward plus
        foundational papers.</p>
        """,
    ),
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID: ToolInfoContent(
        key="harmonic_method_significant_only",
        title="Significant harmonics only",
        html="""
        <p>Includes only harmonics detected above nearby noise (z &gt; 1.64).
        Gaps are left out, and frequencies overlapping the base rate are
        excluded. The resulting list is used for everyone.</p>
        <p>Groups and conditions receive equal weight when choosing the list.
        Because the same data select and test the response, treat findings as
        exploratory; this threshold does not correct for searching many
        harmonics.</p>
        <p><b>Publications using significance-based selection</b><br>
        These studies select individual significant harmonics; the differences
        below matter when comparing results.</p>
        <ul>
        <li><a href="https://doi.org/10.1038/s41467-025-62210-1">Huang et al.
        (2025) — Conceptual knowledge increasingly supports emotion understanding
        as perceptual contribution declines with age</a>.<br>
        Required significance in every age group (3.6 and 4.8 Hz); analyzed SNR.
        This differs from the Toolbox's balanced selection and summed BCA.</li>
        <li><a href="https://doi.org/10.1111/psyp.14725">Naumann et al. (2025)
        — Preschoolers' responses to happy and angry expressions</a>.<br>
        Selects significant harmonics at z &gt; 1.64 in the maximum-intensity
        task. The graded-intensity task instead reuses that selected list.</li>
        <li><a href="https://doi.org/10.1016/j.cortex.2024.01.007">Lochy et al.
        (2024) — Linguistic and attentional contributions to word-selective
        responses</a>.<br>
        Sums significant harmonics using z &gt; 3.1 and separate condition
        averages, rather than the Toolbox's z &gt; 1.64 common selector.</li>
        </ul>
        <p>References checked October 2026, focusing on 2020 onward.</p>
        """,
    ),
    HARMONIC_PROFILE_LEGACY_ID: ToolInfoContent(
        key="harmonic_method_legacy",
        title="Legacy Toolbox selection",
        html="""
        <p>Reproduces the selection used by older Toolbox projects. It includes
        eligible harmonics through the highest detected response, with a rule
        that drops an isolated highest peak when more than ten eligible
        harmonics separate it from the next detection.</p>
        <p>Available workbooks receive equal weight, and the saved electrode
        selection is retained. Base-rate overlaps are excluded. Keep this
        option when reproducing earlier results.</p>
        <p><b>Publications</b><br>
        No publication was verified for this exact Toolbox rule, including its
        isolated-peak guard. It should be reported as a Toolbox compatibility
        method.</p>
        """,
    ),
}


def build_harmonic_page(self, tabs: QTabWidget) -> QWidget:
    tab = QWidget()
    tab.setObjectName("settings_harmonics_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    project_pp = self._project_preprocessing() if self.project else None
    self._add_harmonic_selection_section(tab, layout, project_pp)

    layout.addStretch(1)
    tabs.addTab(tab, "Harmonics")
    return tab


def add_harmonic_selection_section(
    self,
    tab: QWidget,
    layout: QVBoxLayout,
    project_pp: Dict[str, Any] | None,
) -> None:
    settings = normalize_dv_policy(self._harmonic_policy_payload_from_preprocessing(project_pp))
    harmonic_group = SectionCard(
        "Harmonic Selection and Summation",
        tab,
        object_name="settings_harmonic_selection_card",
    )
    harmonic_form = make_form_layout()

    self.harmonic_summation_method_combo = QComboBox(harmonic_group)
    self.harmonic_summation_method_combo.setObjectName(
        "settings_harmonic_summation_method"
    )
    self.harmonic_summation_method_combo.addItem(
        "Stop after two consecutive failures (recommended)",
        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    )
    self.harmonic_summation_method_combo.addItem(
        "Fixed / preregistered harmonic domain",
        HARMONIC_PROFILE_FIXED_ID,
    )
    self.harmonic_summation_method_combo.addItem(
        "Significant harmonics only (exploratory)",
        HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    )
    self.harmonic_summation_method_combo.addItem(
        "Legacy Toolbox selection",
        HARMONIC_PROFILE_LEGACY_ID,
    )
    method_index = self.harmonic_summation_method_combo.findData(
        settings.harmonic_selection_profile
    )
    self.harmonic_summation_method_combo.setCurrentIndex(max(0, method_index))
    self.harmonic_summation_method_combo.setToolTip(
        "Choose the versioned rule that defines the common oddball harmonics "
        "summed into BCA for every downstream analysis."
    )
    method_row = QWidget(harmonic_group)
    method_layout = QHBoxLayout(method_row)
    method_layout.setContentsMargins(0, 0, 0, 0)
    method_layout.setSpacing(8)
    method_layout.addWidget(self.harmonic_summation_method_combo, 1)
    self.harmonic_method_info_button = make_info_button(
        parent=method_row,
        object_name="settings_harmonic_method_info",
        tooltip="About the selected harmonic method and its publications",
        size=16,
    )
    self.harmonic_method_info_button.clicked.connect(self._show_harmonic_method_info)
    method_layout.addWidget(self.harmonic_method_info_button)
    harmonic_form.addRow(QLabel("Method profile:", harmonic_group), method_row)

    self.harmonic_electrode_scope_combo = QComboBox(harmonic_group)
    self.harmonic_electrode_scope_combo.setObjectName(
        "settings_harmonic_electrode_scope"
    )
    self.harmonic_electrode_scope_combo.addItem(
        "All retained scalp electrodes",
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
    )
    self.harmonic_electrode_scope_combo.addItem(
        "Frozen custom electrode mask",
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
    )
    self.harmonic_electrode_scope_combo.addItem(
        "Legacy only: current Stats ROI union",
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    )
    scope_index = self.harmonic_electrode_scope_combo.findData(
        settings.group_significant_electrode_scope
    )
    self.harmonic_electrode_scope_combo.setCurrentIndex(max(0, scope_index))
    self.harmonic_electrode_scope_combo.setToolTip(
        "Adaptive profiles use this fixed electrode set to build the selection "
        "spectrum. A frozen mask prevents later ROI edits from changing the method."
    )
    harmonic_form.addRow(
        QLabel("Selection electrodes:", harmonic_group),
        self.harmonic_electrode_scope_combo,
    )

    self.harmonic_selection_electrodes_edit = QLineEdit(
        ", ".join(settings.group_significant_selection_electrodes),
        harmonic_group,
    )
    self.harmonic_selection_electrodes_edit.setObjectName(
        "settings_harmonic_selection_electrodes"
    )
    self.harmonic_selection_electrodes_edit.setPlaceholderText(
        "O1, Oz, O2, PO7, PO8"
    )
    self.harmonic_selection_electrodes_edit.setToolTip(
        "Comma-separated electrode names stored with the method and fingerprint."
    )
    harmonic_form.addRow(
        QLabel("Frozen electrode mask:", harmonic_group),
        self.harmonic_selection_electrodes_edit,
    )

    self.fixed_harmonic_input_mode_combo = QComboBox(harmonic_group)
    self.fixed_harmonic_input_mode_combo.setObjectName(
        "settings_fixed_harmonic_input_mode"
    )
    self.fixed_harmonic_input_mode_combo.addItem(
        "Exact frequency list",
        FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
    )
    self.fixed_harmonic_input_mode_combo.addItem(
        "All eligible harmonics through harmonic index",
        FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
    )
    self.fixed_harmonic_input_mode_combo.addItem(
        "All eligible harmonics through frequency",
        FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
    )
    fixed_mode_index = self.fixed_harmonic_input_mode_combo.findData(
        settings.fixed_harmonic_input_mode
    )
    self.fixed_harmonic_input_mode_combo.setCurrentIndex(
        max(0, fixed_mode_index)
    )
    harmonic_form.addRow(
        QLabel("Fixed-domain input:", harmonic_group),
        self.fixed_harmonic_input_mode_combo,
    )

    self.fixed_harmonic_freqs_edit = QLineEdit(
        str(settings.fixed_harmonic_frequencies_hz),
        harmonic_group,
    )
    self.fixed_harmonic_freqs_edit.setObjectName("settings_fixed_harmonics")
    self.fixed_harmonic_freqs_edit.setPlaceholderText("1.2, 2.4, 3.6, 4.8, 7.2")
    self.fixed_harmonic_freqs_edit.setToolTip(
        "Comma-separated harmonic frequencies in Hz. Used only when Fixed harmonic list is selected."
    )
    harmonic_form.addRow(
        QLabel("Exact frequencies (Hz):", harmonic_group),
        self.fixed_harmonic_freqs_edit,
    )

    self.fixed_harmonic_upper_index_edit = QLineEdit(
        ""
        if settings.fixed_harmonic_upper_harmonic_index is None
        else str(settings.fixed_harmonic_upper_harmonic_index),
        harmonic_group,
    )
    self.fixed_harmonic_upper_index_edit.setObjectName(
        "settings_fixed_harmonic_upper_index"
    )
    self.fixed_harmonic_upper_index_edit.setPlaceholderText("14")
    self.fixed_harmonic_upper_index_edit.setToolTip(
        "Include eligible oddball harmonic orders from 1 through this index."
    )
    harmonic_form.addRow(
        QLabel("Upper harmonic index:", harmonic_group),
        self.fixed_harmonic_upper_index_edit,
    )

    self.fixed_harmonic_upper_frequency_edit = QLineEdit(
        ""
        if settings.fixed_harmonic_upper_frequency_hz is None
        else f"{settings.fixed_harmonic_upper_frequency_hz:g}",
        harmonic_group,
    )
    self.fixed_harmonic_upper_frequency_edit.setObjectName(
        "settings_fixed_harmonic_upper_frequency"
    )
    self.fixed_harmonic_upper_frequency_edit.setPlaceholderText(
        "Optional within project range"
    )
    self.fixed_harmonic_upper_frequency_edit.setToolTip(
        "Include eligible oddball harmonics at or below this prespecified frequency."
    )
    harmonic_form.addRow(
        QLabel("Upper frequency (Hz):", harmonic_group),
        self.fixed_harmonic_upper_frequency_edit,
    )

    self.fixed_harmonic_exclude_base_check = QCheckBox(
        "Base-rate overlaps are always excluded",
        harmonic_group,
    )
    self.fixed_harmonic_exclude_base_check.setObjectName(
        "settings_fixed_harmonics_exclude_base"
    )
    self.fixed_harmonic_exclude_base_check.setChecked(True)
    self.fixed_harmonic_exclude_base_check.setEnabled(False)
    self.fixed_harmonic_exclude_base_check.setToolTip(
        "Oddball harmonics that overlap the base stimulation frequency or "
        "its harmonics cannot enter the fixed oddball composite."
    )
    harmonic_form.addRow("", self.fixed_harmonic_exclude_base_check)

    harmonic_group.content_layout.addLayout(harmonic_form)
    self.fixed_harmonic_warning = StatusBanner(
        "",
        harmonic_group,
        variant="info",
    )
    self.fixed_harmonic_warning.setObjectName("settings_fixed_harmonic_warning")
    self.fixed_harmonic_warning.setVisible(True)
    harmonic_group.content_layout.addWidget(self.fixed_harmonic_warning)
    harmonic_actions = ActionRow(harmonic_group, alignment=Qt.AlignLeft)
    harmonic_actions.setObjectName("settings_harmonic_selection_actions")
    self.recalculate_harmonics_button = make_action_button(
        "Recalculate Harmonics",
        compact=True,
        parent=harmonic_group,
    )
    self.recalculate_harmonics_button.setObjectName(
        "settings_recalculate_harmonics_button"
    )
    self.recalculate_harmonics_button.setToolTip(
        "Recalculate the project's harmonic domain from existing processed "
        "workbooks, then rebuild every Summed-BCA derivative. Raw EEG "
        "preprocessing and FFT export are not rerun."
    )
    self.recalculate_harmonics_button.setEnabled(self.project is not None)
    self.recalculate_harmonics_button.clicked.connect(
        self._on_recalculate_harmonics_clicked
    )
    self.review_condition_exclusions_button = make_action_button(
        "Review FFT Crop Exclusions",
        compact=True,
        parent=harmonic_group,
    )
    self.review_condition_exclusions_button.setObjectName(
        "settings_review_condition_exclusions_button"
    )
    self.review_condition_exclusions_button.setToolTip(
        "Check processed FullFFT grids and exclude selected participant-condition "
        "pairs, including conditions with no input in the last Processing run."
    )
    self.review_condition_exclusions_button.setEnabled(self.project is not None)
    self.review_condition_exclusions_button.clicked.connect(
        self._on_review_condition_exclusions_clicked
    )
    harmonic_actions.add_button(self.recalculate_harmonics_button)
    harmonic_actions.add_button(self.review_condition_exclusions_button)
    harmonic_group.content_layout.addWidget(harmonic_actions)

    self.harmonic_recalculation_status = StatusBanner("", harmonic_group, variant="info")
    self.harmonic_recalculation_status.setObjectName(
        "settings_harmonic_recalculation_status"
    )
    self.harmonic_recalculation_status.setVisible(False)
    harmonic_group.content_layout.addWidget(self.harmonic_recalculation_status)

    layout.addWidget(harmonic_group)
    self.harmonic_summation_method_combo.currentIndexChanged.connect(
        self._update_harmonic_selection_controls
    )
    self.harmonic_electrode_scope_combo.currentIndexChanged.connect(
        self._update_harmonic_selection_controls
    )
    self.fixed_harmonic_input_mode_combo.currentIndexChanged.connect(
        self._update_harmonic_selection_controls
    )
    self._update_harmonic_selection_controls()
