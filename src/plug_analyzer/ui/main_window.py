"""Native Qt main window for the local Plug Analyzer workflow."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from plug_analyzer.ui.view_models import (
    AnalysisResultDisplay,
    AppState,
    ChoiceDisplay,
    NoticeLevel,
    PreflightSummary,
    SavedMetricComparisonDisplay,
    SourceSummary,
    StorageSummary,
    metric_label,
)
from plug_analyzer.ui.widgets import (
    AnalysisParameterEditor,
    NoticeBanner,
    ResultCharts,
    ZStackViewer,
    format_bytes,
)

APP_STYLESHEET = """
QMainWindow, QWidget { color: #243244; font-size: 13px; background-color: #f4f6f8; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QCheckBox, QRadioButton { spacing: 7px; color: #243244; }
QCheckBox:disabled, QRadioButton:disabled { color: #8c98a3; }
QMainWindow, QDialog, QStackedWidget { background: #f4f6f8; }
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
  background: #f4f6f8; border: 0;
}
QFrame#sidebar { background: #172331; border: 0; }
QFrame#sidebar QLabel { color: #f4f7fb; }
QListWidget#navigation { background: transparent; color: #cbd5e1; border: 0; outline: 0; }
QListWidget#navigation::item { padding: 11px 12px; margin: 2px 7px; border-radius: 6px; }
QListWidget#navigation::item:selected { background: #2b6f9f; color: white; }
QListWidget#navigation::item:disabled { color: #637385; }
QFrame#pageHeader { background: white; border-bottom: 1px solid #dbe2e8; }
QFrame#contentCard, QGroupBox {
  background: white; border: 1px solid #dce3e9; border-radius: 8px;
}
QFrame#viewerToolbar, QFrame#polygonTools, QFrame#displayTools {
  background: #f7f9fb; border: 1px solid #dce3e9; border-radius: 6px;
}
QFrame#zNavigation { background: white; border: 1px solid #dce3e9; border-radius: 6px; }
QDialog#polygonTools, QDialog#displayTools { background: #f7f9fb; }
QGroupBox { margin-top: 13px; padding: 12px 9px 9px 9px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #1f3142; background: #f4f6f8; }
QLabel[class="pageTitle"] { font-size: 21px; font-weight: 650; color: #152331; }
QLabel[class="pageSubtitle"] { color: #627184; }
QLabel[class="sectionTitle"] { font-size: 14px; font-weight: 650; color: #1f3142; }
QLabel[class="helpText"] { color: #66768a; font-size: 12px; }
QLabel#statusPill { background: #e8f1f8; color: #22597d; padding: 5px 10px; border-radius: 10px; }
QPushButton { background: #f7f9fb; border: 1px solid #c9d4dd; border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #edf3f7; }
QPushButton:pressed { background: #e1eaf0; }
QPushButton:disabled { color: #9ca8b2; background: #f2f4f5; border-color: #e0e4e7; }
QPushButton[class="primary"] { background: #276e9d; color: white; border-color: #276e9d; font-weight: 600; }
QPushButton[class="primary"]:hover { background: #205f88; }
QPushButton[class="danger"] { color: #96333a; }
QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox, QSpinBox {
  color: #243244; background: white; border: 1px solid #bdc9d3; border-radius: 4px; padding: 5px;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { min-height: 22px; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {
  border: 1px solid #347eae;
}
QTableView, QTableWidget {
  color: #243244; background: white; alternate-background-color: #f7f9fb;
  selection-background-color: #d9ebf6; selection-color: #152331;
  gridline-color: #e4e9ed; border: 1px solid #d7e0e7;
}
QHeaderView::section { background: #eef3f6; color: #33485b; padding: 6px; border: 0; border-right: 1px solid #d7e0e7; font-weight: 600; }
QTableCornerButton::section { background: #eef3f6; border: 0; }
QProgressBar { border: 1px solid #c8d2da; border-radius: 5px; background: #edf1f4; text-align: center; }
QProgressBar::chunk { background: #2d82b4; border-radius: 4px; }
QMenuBar { color: #243244; background: #ffffff; border-bottom: 1px solid #dbe2e8; }
QMenuBar::item:selected { background: #e8f1f8; }
QMenu { color: #243244; background: #ffffff; border: 1px solid #c9d4dd; }
QMenu::item:selected { color: #152331; background: #d9ebf6; }
QToolTip { color: #243244; background: #ffffff; border: 1px solid #aebbc6; }
QTabWidget::pane { background: white; border: 1px solid #dce3e9; border-radius: 6px; top: -1px; }
QTabBar::tab {
  color: #526578; background: #edf2f5; border: 1px solid #dce3e9;
  padding: 8px 10px; margin-right: 2px;
}
QTabBar::tab:selected { color: #1f5579; background: white; border-bottom-color: white; font-weight: 600; }
QSplitter::handle { background: #dce3e9; }
QScrollBar:vertical {
  background: #edf1f4; width: 12px; margin: 0; border: 0;
}
QScrollBar::handle:vertical {
  background: #aebbc6; min-height: 28px; margin: 2px; border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: #8fa0ad; }
QScrollBar:horizontal {
  background: #edf1f4; height: 12px; margin: 0; border: 0;
}
QScrollBar::handle:horizontal {
  background: #aebbc6; min-width: 28px; margin: 2px; border-radius: 4px;
}
QScrollBar::handle:horizontal:hover { background: #8fa0ad; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; background: transparent; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal {
  height: 5px; background: #d3dce3; border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #4c91bb; border-radius: 2px; }
QSlider::handle:horizontal {
  background: #ffffff; border: 1px solid #718595; width: 15px;
  margin: -6px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { border-color: #2b78a7; background: #edf6fb; }
"""


class MainWindow(QMainWindow):
    """Four-page workflow shell driven by controller-friendly signals and setters."""

    createProjectRequested = Signal(str)
    openProjectRequested = Signal(str)
    sourceImportRequested = Signal(str)
    analyzeRequested = Signal(dict)
    cancelRequested = Signal()
    saveResultRequested = Signal()
    exportCsvRequested = Signal(str)
    exportJsonRequested = Signal(str)
    exportPngRequested = Signal(str)
    clearCacheRequested = Signal()
    revealStorageRequested = Signal(str)
    planeRequested = Signal(int)
    orthogonalPositionRequested = Signal(int, int)
    sampleSelectedRequested = Signal(str)
    savedRunsCompareRequested = Signal(str, str)
    dimensionSelectionChanged = Signal(dict)
    closing = Signal()

    PAGE_HOME = 0
    PAGE_IMPORT = 1
    PAGE_ANALYZE = 2
    PAGE_RESULTS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("Plug Analyzer")
        self.resize(1320, 820)
        self.setMinimumSize(1000, 680)
        self._state = AppState()
        self._preflight_safe = False
        self._result: AnalysisResultDisplay | None = None
        self._source_path: Path | None = None

        self.setStyleSheet(APP_STYLESHEET)
        self._build_actions()
        self._build_shell()
        self._build_home_page()
        self._build_import_page()
        self._build_analyze_page()
        self._build_results_page()
        self._connect_actions()
        self.set_state(self._state)

    # ---------- construction ----------

    def _build_actions(self) -> None:
        self.new_project_action = QAction("New project…", self)
        self.open_project_action = QAction("Open project…", self)
        self.import_source_action = QAction("Import microscope source…", self)
        self.quit_action = QAction("Quit", self)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.new_project_action)
        file_menu.addAction(self.open_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_source_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

    def _build_shell(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 17, 8, 14)
        brand = QLabel("PLUG ANALYZER")
        brand.setFont(QFont("", 15, QFont.Weight.Bold))
        brand.setContentsMargins(10, 0, 0, 7)
        subtitle = QLabel("Local microscope analysis")
        subtitle.setStyleSheet("color: #91a3b5; font-size: 11px;")
        subtitle.setContentsMargins(10, 0, 0, 14)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(subtitle)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setSpacing(2)
        for name in ("1  Project", "2  Import", "3  Analyze", "4  Results"):
            self.navigation.addItem(QListWidgetItem(name))
        self.navigation.setCurrentRow(self.PAGE_HOME)
        sidebar_layout.addWidget(self.navigation, 1)
        local_label = QLabel("Runs locally • No cloud upload")
        local_label.setWordWrap(True)
        local_label.setStyleSheet("color: #8da1b4; font-size: 11px; padding: 8px;")
        sidebar_layout.addWidget(local_label)
        root_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("pageHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 12, 22, 12)
        header_top = QHBoxLayout()
        self.page_title = QLabel("Project")
        self.page_title.setProperty("class", "pageTitle")
        self.status_pill = QLabel("Ready")
        self.status_pill.setObjectName("statusPill")
        header_top.addWidget(self.page_title)
        header_top.addStretch(1)
        header_top.addWidget(self.status_pill)
        header_layout.addLayout(header_top)
        self.notice = NoticeBanner()
        header_layout.addWidget(self.notice)
        content_layout.addWidget(header)
        self.pages = QStackedWidget()
        self.pages.setObjectName("workflowPages")
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(content, 1)

    @staticmethod
    def _page_shell(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setProperty("class", "sectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setProperty("class", "pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return page, layout

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("contentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(17, 15, 17, 15)
        layout.setSpacing(11)
        return card, layout

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_home_page(self) -> None:
        page, layout = self._page_shell(
            "Start with a local project",
            "A project keeps source links, settings, saved results, and cache files together in "
            "one visible folder on this computer.",
        )
        card, card_layout = self._card()
        project_title = QLabel("Project location")
        project_title.setProperty("class", "sectionTitle")
        card_layout.addWidget(project_title)
        self.project_path_edit = QLineEdit()
        self.project_path_edit.setObjectName("projectPathEdit")
        self.project_path_edit.setReadOnly(True)
        self.project_path_edit.setPlaceholderText("No project open")
        card_layout.addWidget(self.project_path_edit)
        buttons = QHBoxLayout()
        self.create_project_button = QPushButton("Create project…")
        self.create_project_button.setObjectName("createProjectButton")
        self.create_project_button.setProperty("class", "primary")
        self.open_project_button = QPushButton("Open existing project…")
        self.open_project_button.setObjectName("openProjectButton")
        buttons.addWidget(self.create_project_button)
        buttons.addWidget(self.open_project_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        self.project_mode_label = QLabel("No project loaded")
        self.project_mode_label.setObjectName("projectModeLabel")
        self.project_mode_label.setProperty("class", "helpText")
        card_layout.addWidget(self.project_mode_label)
        storage_row = QHBoxLayout()
        self.project_storage_label = QLabel("Project size: —")
        self.project_storage_label.setObjectName("projectStorageLabel")
        self.project_storage_label.setProperty("class", "helpText")
        self.reveal_storage_button = QPushButton("Show project folder")
        self.reveal_storage_button.setObjectName("revealStorageButton")
        self.clear_cache_button = QPushButton("Remove cached image data…")
        self.clear_cache_button.setObjectName("clearCacheButton")
        storage_row.addWidget(self.project_storage_label)
        storage_row.addStretch(1)
        storage_row.addWidget(self.reveal_storage_button)
        storage_row.addWidget(self.clear_cache_button)
        card_layout.addLayout(storage_row)
        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel("Current sample"))
        self.sample_selector = QComboBox()
        self.sample_selector.setObjectName("sampleSelector")
        self.sample_selector.setMinimumWidth(300)
        self.open_sample_button = QPushButton("Open sample")
        self.open_sample_button.setObjectName("openSampleButton")
        sample_row.addWidget(self.sample_selector, 1)
        sample_row.addWidget(self.open_sample_button)
        card_layout.addLayout(sample_row)
        layout.addWidget(card)

        workflow, workflow_layout = self._card()
        workflow_title = QLabel("Prototype workflow")
        workflow_title.setProperty("class", "sectionTitle")
        workflow_layout.addWidget(workflow_title)
        workflow_layout.addWidget(
            QLabel(
                "1. Create/open project  →  2. Inspect TIFF or ND2  →  3. Confirm parameters and "
                "analyze  →  4. Review, save, and compare app runs"
            )
        )
        scientific_scope = QLabel(
            "This prototype quantifies fluorescence-defined plug formation. It does not by itself "
            "prove that flow or sweating is blocked; functional confirmation needs an independent "
            "flow or pressure measurement."
        )
        scientific_scope.setWordWrap(True)
        scientific_scope.setProperty("class", "helpText")
        workflow_layout.addWidget(scientific_scope)
        layout.addWidget(workflow)
        layout.addStretch(1)
        home_scroll = self._scroll_page(page)
        home_scroll.setObjectName("homeScroll")
        self.pages.addWidget(home_scroll)

    def _build_import_page(self) -> None:
        page, layout = self._page_shell(
            "Import and inspect a microscope source",
            "The source remains on this computer. TIFF/OME-TIFF and Nikon ND2 are inspected before "
            "any analysis begins.",
        )
        source_card, source_layout = self._card()
        source_row = QHBoxLayout()
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setObjectName("sourcePathEdit")
        self.source_path_edit.setPlaceholderText("Choose .tif, .tiff, .ome.tif, or .nd2")
        self.browse_source_button = QPushButton("Browse…")
        self.browse_source_button.setObjectName("browseSourceButton")
        self.inspect_source_button = QPushButton("Inspect source")
        self.inspect_source_button.setObjectName("inspectSourceButton")
        self.inspect_source_button.setProperty("class", "primary")
        source_row.addWidget(self.source_path_edit, 1)
        source_row.addWidget(self.browse_source_button)
        source_row.addWidget(self.inspect_source_button)
        source_layout.addLayout(source_row)
        self.source_hint_label = QLabel("No source inspected")
        self.source_hint_label.setObjectName("sourceHintLabel")
        self.source_hint_label.setProperty("class", "helpText")
        source_layout.addWidget(self.source_hint_label)
        selection_row = QHBoxLayout()
        selection_row.addWidget(QLabel("Scene"))
        self.scene_spin = self._dimension_spin("sceneSpin")
        selection_row.addWidget(self.scene_spin)
        selection_row.addWidget(QLabel("Time"))
        self.time_spin = self._dimension_spin("timeSpin")
        selection_row.addWidget(self.time_spin)
        selection_row.addWidget(QLabel("Channel"))
        self.channel_spin = self._dimension_spin("channelSpin")
        selection_row.addWidget(self.channel_spin)
        selection_row.addWidget(QLabel("Z start"))
        self.z_start_spin = self._dimension_spin("zStartSpin")
        selection_row.addWidget(self.z_start_spin)
        selection_row.addWidget(QLabel("Z stop"))
        self.z_stop_spin = self._dimension_spin("zStopSpin")
        self.z_stop_spin.setSpecialValueText("All")
        selection_row.addWidget(self.z_stop_spin)
        selection_row.addStretch(1)
        source_layout.addLayout(selection_row)
        selection_help = QLabel(
            "Indices are zero-based. Z stop is exclusive; leave it at All to process every Z "
            "plane. Change a selection, then inspect again before analysis."
        )
        selection_help.setProperty("class", "helpText")
        selection_help.setWordWrap(True)
        source_layout.addWidget(selection_help)
        layout.addWidget(source_card)

        columns = QSplitter(Qt.Orientation.Horizontal)
        metadata_group = QGroupBox("Detected metadata")
        metadata_layout = QVBoxLayout(metadata_group)
        self.metadata_table = QTableWidget(0, 2)
        self.metadata_table.setObjectName("metadataTable")
        self.metadata_table.setHorizontalHeaderLabels(("Field", "Value"))
        self.metadata_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metadata_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.metadata_table.verticalHeader().hide()
        self.metadata_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.metadata_table.setAlternatingRowColors(True)
        metadata_layout.addWidget(self.metadata_table)
        columns.addWidget(metadata_group)

        preflight_group = QGroupBox("Resource preflight")
        preflight_layout = QVBoxLayout(preflight_group)
        self.preflight_status = QLabel("Inspect a source to calculate a safe processing plan.")
        self.preflight_status.setObjectName("preflightStatusLabel")
        self.preflight_status.setWordWrap(True)
        preflight_layout.addWidget(self.preflight_status)
        self.preflight_table = QTableWidget(0, 2)
        self.preflight_table.setObjectName("preflightTable")
        self.preflight_table.setHorizontalHeaderLabels(("Resource", "Plan"))
        self.preflight_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.preflight_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.preflight_table.verticalHeader().hide()
        self.preflight_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preflight_layout.addWidget(self.preflight_table)
        self.preflight_warnings = QLabel("")
        self.preflight_warnings.setObjectName("preflightWarningsLabel")
        self.preflight_warnings.setWordWrap(True)
        self.preflight_warnings.setProperty("class", "helpText")
        preflight_layout.addWidget(self.preflight_warnings)
        columns.addWidget(preflight_group)
        columns.setSizes((570, 430))
        layout.addWidget(columns, 1)
        self.pages.addWidget(page)

    def _build_analyze_page(self) -> None:
        page, layout = self._page_shell(
            "Review the stack and analysis setup",
            "Inspect the linked planes, confirm calibration and regions, then run the locked "
            "deterministic method.",
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("analysisSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        viewer_card, viewer_layout = self._card()
        viewer_layout.setContentsMargins(12, 12, 12, 10)
        self.viewer = ZStackViewer()
        self.viewer.setMinimumHeight(535)
        viewer_layout.addWidget(self.viewer)
        splitter.addWidget(viewer_card)

        parameter_scroll = QScrollArea()
        parameter_scroll.setWidgetResizable(True)
        parameter_scroll.setMinimumWidth(350)
        parameter_scroll.setMaximumWidth(400)
        parameter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parameter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        parameter_scroll.setObjectName("analysisParameterScroll")
        parameter_card, parameter_layout = self._card()
        self.parameter_editor = AnalysisParameterEditor()
        parameter_layout.addWidget(self.parameter_editor)

        run_group = QGroupBox("Run analysis")
        run_group.setObjectName("runAnalysisGroup")
        run_layout = QVBoxLayout(run_group)
        run_layout.setSpacing(8)
        readiness = QLabel(
            "Check calibration and the blue analysis and green background outlines in the image, "
            "then run the fixed prototype method."
        )
        readiness.setWordWrap(True)
        readiness.setProperty("class", "helpText")
        run_layout.addWidget(readiness)

        run_row = QHBoxLayout()
        self.run_analysis_button = QPushButton("Run analysis")
        self.run_analysis_button.setObjectName("runAnalysisButton")
        self.run_analysis_button.setProperty("class", "primary")
        self.cancel_analysis_button = QPushButton("Cancel")
        self.cancel_analysis_button.setObjectName("cancelAnalysisButton")
        self.cancel_analysis_button.setProperty("class", "danger")
        self.view_results_button = QPushButton("View results")
        self.view_results_button.setObjectName("viewResultsButton")
        run_row.addWidget(self.run_analysis_button, 1)
        run_row.addWidget(self.cancel_analysis_button)
        run_layout.addLayout(run_row)
        run_layout.addWidget(self.view_results_button)

        self.progress_label = QLabel("Ready to analyze")
        self.progress_label.setObjectName("analysisProgressLabel")
        self.progress_label.setWordWrap(True)
        self.progress_label.setProperty("class", "helpText")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("analysisProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setToolTip("Shows how far the current import or analysis has progressed.")
        run_layout.addWidget(self.progress_label)
        run_layout.addWidget(self.progress_bar)

        self.parameter_editor.add_run_controls(run_group)
        parameter_scroll.setWidget(parameter_card)
        splitter.addWidget(parameter_scroll)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((980, 340))
        layout.addWidget(splitter, 1)
        self.pages.addWidget(page)

    def _build_results_page(self) -> None:
        content, layout = self._page_shell(
            "Review, save, and compare results",
            "Results remain previews until you explicitly save them. Exports contain the displayed "
            "values and protocol context; the source pixels are not embedded in CSV/JSON exports.",
        )
        result_header, result_header_layout = self._card()
        header_row = QHBoxLayout()
        self.result_identity = QLabel("No analysis result")
        self.result_identity.setObjectName("resultIdentityLabel")
        self.result_identity.setProperty("class", "sectionTitle")
        self.save_result_button = QPushButton("Save result")
        self.save_result_button.setObjectName("saveResultButton")
        self.save_result_button.setProperty("class", "primary")
        self.export_csv_button = QPushButton("Export CSV…")
        self.export_csv_button.setObjectName("exportCsvButton")
        self.export_json_button = QPushButton("Export JSON…")
        self.export_json_button.setObjectName("exportJsonButton")
        self.export_png_button = QPushButton("Export figure PNG…")
        self.export_png_button.setObjectName("exportPngButton")
        self.copy_metrics_button = QPushButton("Copy metrics")
        self.copy_metrics_button.setObjectName("copyMetricsButton")
        header_row.addWidget(self.result_identity)
        header_row.addStretch(1)
        header_row.addWidget(self.save_result_button)
        header_row.addWidget(self.export_csv_button)
        header_row.addWidget(self.export_json_button)
        header_row.addWidget(self.export_png_button)
        header_row.addWidget(self.copy_metrics_button)
        result_header_layout.addLayout(header_row)
        self.result_qc_label = QLabel("")
        self.result_qc_label.setObjectName("resultQcLabel")
        self.result_qc_label.setWordWrap(True)
        self.result_qc_label.setProperty("class", "helpText")
        result_header_layout.addWidget(self.result_qc_label)
        layout.addWidget(result_header)

        metric_group = QGroupBox("Summary metrics")
        metric_layout = QVBoxLayout(metric_group)
        self.metric_table = QTableWidget(0, 5)
        self.metric_table.setObjectName("metricTable")
        self.metric_table.setHorizontalHeaderLabels(
            ("Metric", "Value", "Unit", "Availability", "Qualification")
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.metric_table.verticalHeader().hide()
        self.metric_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.metric_table.setAlternatingRowColors(True)
        metric_layout.addWidget(self.metric_table)
        layout.addWidget(metric_group)

        chart_group = QGroupBox("Per-Z profiles")
        chart_layout = QVBoxLayout(chart_group)
        self.result_charts = ResultCharts()
        self.result_charts.setMinimumHeight(420)
        chart_layout.addWidget(self.result_charts)
        layout.addWidget(chart_group)

        saved_compare_group = QGroupBox("Compare two saved runs")
        saved_compare_layout = QVBoxLayout(saved_compare_group)
        saved_compare_help = QLabel(
            "Choose two results saved by Plug Analyzer in this project. Run A is the starting "
            "point. Change is Run B minus Run A."
        )
        saved_compare_help.setWordWrap(True)
        saved_compare_help.setProperty("class", "helpText")
        saved_compare_layout.addWidget(saved_compare_help)
        saved_compare_controls = QHBoxLayout()
        self.left_run_selector = QComboBox()
        self.left_run_selector.setObjectName("leftRunSelector")
        self.right_run_selector = QComboBox()
        self.right_run_selector.setObjectName("rightRunSelector")
        self.compare_saved_runs_button = QPushButton("Compare saved runs")
        self.compare_saved_runs_button.setObjectName("compareSavedRunsButton")
        saved_compare_controls.addWidget(QLabel("Run A"))
        saved_compare_controls.addWidget(self.left_run_selector, 1)
        saved_compare_controls.addWidget(QLabel("Run B"))
        saved_compare_controls.addWidget(self.right_run_selector, 1)
        saved_compare_controls.addWidget(self.compare_saved_runs_button)
        saved_compare_layout.addLayout(saved_compare_controls)
        self.compatibility_label = QLabel("Choose two saved runs to compare.")
        self.compatibility_label.setObjectName("comparisonCompatibilityLabel")
        self.compatibility_label.setWordWrap(True)
        self.compatibility_label.setProperty("class", "helpText")
        saved_compare_layout.addWidget(self.compatibility_label)
        self.saved_run_comparison_table = QTableWidget(0, 6)
        self.saved_run_comparison_table.setObjectName("savedRunComparisonTable")
        self.saved_run_comparison_table.setHorizontalHeaderLabels(
            ("Metric", "Run A", "Run B", "Change (B - A)", "Unit", "Note")
        )
        for column in range(5):
            self.saved_run_comparison_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.saved_run_comparison_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.saved_run_comparison_table.verticalHeader().hide()
        self.saved_run_comparison_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.saved_run_comparison_table.setAlternatingRowColors(True)
        saved_compare_layout.addWidget(self.saved_run_comparison_table)
        self.copy_comparison_button = QPushButton("Copy comparison table")
        self.copy_comparison_button.setObjectName("copyComparisonButton")
        saved_compare_layout.addWidget(
            self.copy_comparison_button, alignment=Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(saved_compare_group)

        limitations = QGroupBox("Interpretation limits")
        limitations_layout = QVBoxLayout(limitations)
        limitations_text = QLabel(
            "• Apparent low-fluorescence fraction is an image-based estimate, not physical "
            "porosity.\n• Compare intensity only when the image channel and acquisition are "
            "matched.\n• Results may be lower bounds when the plug touches an image edge.\n"
            "• Confirm functional clogging with a separate flow or pressure test."
        )
        limitations_text.setWordWrap(True)
        limitations_layout.addWidget(limitations_text)
        layout.addWidget(limitations)
        layout.addStretch(1)
        self.pages.addWidget(self._scroll_page(content))

    def _connect_actions(self) -> None:
        self.navigation.currentRowChanged.connect(self._change_page)
        self.new_project_action.triggered.connect(self._choose_create_project)
        self.open_project_action.triggered.connect(self._choose_open_project)
        self.import_source_action.triggered.connect(self._choose_source)
        self.quit_action.triggered.connect(QApplication.closeAllWindows)
        self.create_project_button.clicked.connect(self._choose_create_project)
        self.open_project_button.clicked.connect(self._choose_open_project)
        self.browse_source_button.clicked.connect(self._choose_source)
        self.inspect_source_button.clicked.connect(self._request_source_import)
        self.run_analysis_button.clicked.connect(self._request_analysis)
        self.cancel_analysis_button.clicked.connect(self.cancelRequested)
        self.save_result_button.clicked.connect(self.saveResultRequested)
        self.export_csv_button.clicked.connect(self._choose_csv_export)
        self.export_json_button.clicked.connect(self._choose_json_export)
        self.export_png_button.clicked.connect(self._choose_png_export)
        self.copy_comparison_button.clicked.connect(self._copy_comparison_table)
        self.copy_metrics_button.clicked.connect(
            lambda: self._copy_table(self.metric_table, "Metric table")
        )
        self.clear_cache_button.clicked.connect(self.clearCacheRequested)
        self.reveal_storage_button.clicked.connect(self._request_reveal_storage)
        self.viewer.planeRequested.connect(self.planeRequested)
        self.viewer.positionRequested.connect(self.orthogonalPositionRequested)
        self.viewer.roiChanged.connect(self._apply_viewer_roi)
        self.viewer.polygonChanged.connect(self._apply_viewer_polygon)
        self.parameter_editor.parametersChanged.connect(self.set_roi_overlays)
        self.open_sample_button.clicked.connect(self._request_sample_selection)
        self.compare_saved_runs_button.clicked.connect(self._request_saved_run_comparison)
        self.view_results_button.clicked.connect(lambda: self.go_to_page(self.PAGE_RESULTS))
        self.result_charts.planeRequested.connect(self._navigate_to_chart_plane)
        for spin in (
            self.scene_spin,
            self.time_spin,
            self.channel_spin,
            self.z_start_spin,
            self.z_stop_spin,
        ):
            spin.valueChanged.connect(self._emit_dimension_selection)

    # ---------- public controller boundary ----------

    @property
    def state(self) -> AppState:
        return self._state

    @staticmethod
    def _dimension_spin(object_name: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName(object_name)
        spin.setRange(0, 1_000_000)
        spin.setMaximumWidth(92)
        return spin

    def set_state(self, state: AppState) -> None:
        self._state = state
        project_text = str(state.project_path) if state.project_path else ""
        self.project_path_edit.setText(project_text)
        self.project_mode_label.setText(
            "Open read-only — saved content cannot be changed"
            if state.project_read_only
            else ("Project ready" if state.project_open else "No project loaded")
        )
        if state.source_path:
            self.set_source_path(state.source_path)
        self.status_pill.setText(state.status)
        self.import_source_action.setEnabled(state.project_open)
        self.new_project_action.setEnabled(not state.analysis_running)
        self.open_project_action.setEnabled(not state.analysis_running)
        self.create_project_button.setEnabled(not state.analysis_running)
        self.open_project_button.setEnabled(not state.analysis_running)
        self._set_nav_enabled(self.PAGE_IMPORT, state.project_open)
        self._set_nav_enabled(self.PAGE_ANALYZE, state.source_ready)
        self._set_nav_enabled(self.PAGE_RESULTS, state.results_ready)
        self.inspect_source_button.setEnabled(state.project_open and not state.analysis_running)
        self.browse_source_button.setEnabled(state.project_open and not state.analysis_running)
        self.run_analysis_button.setEnabled(
            state.source_ready
            and self._preflight_safe
            and not state.analysis_running
            and not state.project_read_only
        )
        self.cancel_analysis_button.setEnabled(state.analysis_running)
        has_result = self._result is not None
        self.save_result_button.setEnabled(has_result and not state.project_read_only)
        self.export_csv_button.setEnabled(has_result)
        self.export_json_button.setEnabled(has_result)
        self.view_results_button.setEnabled(has_result)
        self.reveal_storage_button.setEnabled(state.project_open)
        self.clear_cache_button.setEnabled(state.project_open and not state.project_read_only)
        self.open_sample_button.setEnabled(state.project_open and self.sample_selector.count() > 0)
        self.compare_saved_runs_button.setEnabled(self.left_run_selector.count() >= 2)

    def set_project_path(
        self, path: str | Path | None, *, read_only: bool = False, status: str = "Project ready"
    ) -> None:
        if path is None:
            self.project_path_edit.clear()
            self.project_mode_label.setText("No project loaded")
            self.project_storage_label.setText("Project size: —")
            self.set_state(AppState(status=status))
            self.go_to_page(self.PAGE_HOME)
            return
        resolved = Path(path)
        self.set_state(
            replace(
                self._state,
                project_path=resolved,
                project_open=True,
                project_read_only=read_only,
                status=status,
            )
        )

    def set_source_path(self, path: str | Path) -> None:
        self._source_path = Path(path)
        self.source_path_edit.setText(str(self._source_path))

    def source_selection(self) -> dict[str, int | None]:
        stop = self.z_stop_spin.value()
        return {
            "scene": self.scene_spin.value(),
            "time": self.time_spin.value(),
            "channel": self.channel_spin.value(),
            "z_start": self.z_start_spin.value(),
            "z_stop": stop or None,
        }

    def set_dimension_limits(
        self,
        *,
        scene_count: int,
        time_count: int,
        channel_count: int,
        z_count: int,
    ) -> None:
        controls = (
            (self.scene_spin, max(0, scene_count - 1)),
            (self.time_spin, max(0, time_count - 1)),
            (self.channel_spin, max(0, channel_count - 1)),
            (self.z_start_spin, max(0, z_count - 1)),
            (self.z_stop_spin, max(0, z_count)),
        )
        for spin, maximum in controls:
            previous = spin.blockSignals(True)
            spin.setMaximum(maximum)
            spin.blockSignals(previous)

    def set_source_selection(self, selection: dict[str, int | None]) -> None:
        for key, spin in (
            ("scene", self.scene_spin),
            ("time", self.time_spin),
            ("channel", self.channel_spin),
            ("z_start", self.z_start_spin),
            ("z_stop", self.z_stop_spin),
        ):
            previous = spin.blockSignals(True)
            spin.setValue(int(selection.get(key) or 0))
            spin.blockSignals(previous)

    def invalidate_preflight(self, message: str) -> None:
        self._preflight_safe = False
        self.preflight_status.setText(message)
        self.preflight_status.setStyleSheet("color: #805810; font-weight: 600;")
        self.preflight_warnings.setText("Inspect the selected dimensions again before analysis.")
        self.set_state(self._state)

    def _emit_dimension_selection(self, *_args: object) -> None:
        self.dimensionSelectionChanged.emit(self.source_selection())

    def set_source_summary(self, summary: SourceSummary) -> None:
        self.source_hint_label.setText(f"Inspected: {summary.filename}")
        rows: list[tuple[str, str]] = [
            ("File", summary.filename),
            ("Format", summary.source_format),
            (
                "Dimensions (Z x Y x X)",
                " x ".join(str(item) for item in summary.dimensions_zyx)
                if summary.dimensions_zyx
                else "Unknown",
            ),
            ("Data type", summary.dtype),
            ("Channel", summary.channel),
            ("Calibration source", summary.calibration_source),
            ("Reader", summary.reader or "Unknown"),
        ]
        x_um, y_um, z_um = summary.calibration_xyz_um
        rows.extend(
            (
                ("X sampling", f"{x_um:g} µm/px" if x_um is not None else "Missing"),
                ("Y sampling", f"{y_um:g} µm/px" if y_um is not None else "Missing"),
                ("Z step", f"{z_um:g} µm" if z_um is not None else "Missing"),
            )
        )
        rows.extend((str(key), str(value)) for key, value in summary.extra.items())
        self._fill_table(self.metadata_table, rows)
        x_value, y_value, z_value = summary.calibration_xyz_um
        if summary.dimensions_zyx:
            _, height, width = summary.dimensions_zyx
            background_height = max(1, height // 10)
            roi_defaults = {
                "analysis_roi_xywh_px": {
                    "x": 0,
                    "y": 0,
                    "width": width,
                    "height": height,
                },
                "background_roi_xywh_px": {
                    "x": 0,
                    "y": 0,
                    "width": width,
                    "height": background_height,
                },
                "envelope_roi_xywh_px": None,
            }
        else:
            roi_defaults = {}
        self.parameter_editor.set_parameters(
            {
                "calibration_xyz_um": (
                    x_value if x_value is not None else 1.0,
                    y_value if y_value is not None else 1.0,
                    z_value if z_value is not None else 1.0,
                ),
                "calibration_confirmed": False,
                **roi_defaults,
            }
        )
        warning_text = "\n".join(f"• {warning}" for warning in summary.warnings)
        if warning_text:
            self.show_notice(warning_text, NoticeLevel.WARNING)

    def set_preflight(self, summary: PreflightSummary) -> None:
        self._preflight_safe = summary.safe_to_start
        rows = (
            ("Available memory", format_bytes(summary.available_memory_bytes)),
            ("Analysis memory budget", format_bytes(summary.memory_budget_bytes)),
            ("Chunk target", format_bytes(summary.compute_chunk_bytes)),
            ("Worker threads", str(summary.worker_threads)),
            ("Free disk", format_bytes(summary.disk_free_bytes)),
            ("Estimated disk required", format_bytes(summary.disk_required_bytes)),
        )
        self._fill_table(self.preflight_table, rows)
        if summary.safe_to_start:
            self.preflight_status.setText("✓ Resource checks passed. Analysis can start.")
            self.preflight_status.setStyleSheet("color: #23643d; font-weight: 600;")
        else:
            self.preflight_status.setText("Analysis is paused because the resource plan is unsafe.")
            self.preflight_status.setStyleSheet("color: #8a2930; font-weight: 600;")
        self.preflight_warnings.setText("\n".join(f"• {item}" for item in summary.warnings))
        self.set_state(self._state)

    def set_analysis_running(self, running: bool, *, status: str | None = None) -> None:
        self.set_state(
            replace(
                self._state,
                analysis_running=running,
                status=status or ("Analyzing" if running else "Ready"),
            )
        )
        if running:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("Starting…")
        elif self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

    def set_analysis_progress(self, percent: int | None, stage: str, detail: str = "") -> None:
        if percent is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, int(percent))))
        text = stage if not detail else f"{stage} — {detail}"
        self.progress_label.setText(text)
        self.status_pill.setText(stage)

    def set_result(self, result: AnalysisResultDisplay) -> None:
        self._result = result
        state_label = "Saved" if result.finalized else "Unsaved preview"
        self.result_identity.setText(f"{result.sample_name}  •  {result.run_id}  •  {state_label}")
        qc_text = result.protocol_label
        if result.qc_summary:
            qc_text += f"  |  QC: {result.qc_summary}"
        self.result_qc_label.setText(qc_text)
        self.metric_table.setRowCount(len(result.metrics))
        for row, metric in enumerate(result.metrics):
            values = (
                metric.name,
                self._format_metric_value(metric.value),
                metric.unit,
                metric.availability.replace("_", " "),
                metric.qualification,
            )
            for column, value in enumerate(values):
                self.metric_table.setItem(row, column, QTableWidgetItem(value))
        if result.planes is None:
            self.result_charts.clear()
        else:
            self.result_charts.set_series(
                result.planes.z_um,
                result.planes.area_um2,
                result.planes.integrated_intensity,
            )
        if result.cross_sections is not None:
            self.result_charts.set_cross_sections(
                result.cross_sections.position_um,
                result.cross_sections.occlusion_percent,
                result.cross_sections.open_area_um2,
            )
        self.set_state(replace(self._state, results_ready=True, status="Results ready"))

    def clear_result(self) -> None:
        self._result = None
        self.result_identity.setText("No analysis result")
        self.result_qc_label.clear()
        self.metric_table.setRowCount(0)
        self.result_charts.clear()
        self.set_state(replace(self._state, results_ready=False))

    def set_storage_summary(self, summary: StorageSummary) -> None:
        self.project_storage_label.setText(
            f"Project size: {format_bytes(summary.total_bytes)} · "
            f"cached images: {format_bytes(summary.cache_bytes)}"
        )

    def set_sample_choices(
        self,
        choices: list[ChoiceDisplay] | tuple[ChoiceDisplay, ...],
        *,
        current_identifier: str | None = None,
    ) -> None:
        self.sample_selector.clear()
        selected = -1
        for index, choice in enumerate(choices):
            self.sample_selector.addItem(choice.label, choice.identifier)
            if choice.identifier == current_identifier:
                selected = index
        if selected >= 0:
            self.sample_selector.setCurrentIndex(selected)
        self.set_state(self._state)

    def set_saved_run_choices(
        self,
        choices: list[ChoiceDisplay] | tuple[ChoiceDisplay, ...],
    ) -> None:
        for selector in (self.left_run_selector, self.right_run_selector):
            selector.clear()
            for choice in choices:
                selector.addItem(choice.label, choice.identifier)
        if len(choices) > 1:
            self.right_run_selector.setCurrentIndex(1)
        self.set_state(self._state)

    def set_saved_run_comparison(
        self,
        rows: list[SavedMetricComparisonDisplay] | tuple[SavedMetricComparisonDisplay, ...],
        *,
        compatibility: str = "",
    ) -> None:
        self.saved_run_comparison_table.setRowCount(len(rows))
        for row_index, comparison in enumerate(rows):
            values = (
                metric_label(comparison.metric_name),
                self._format_metric_value(comparison.left_value),
                self._format_metric_value(comparison.right_value),
                self._format_metric_value(comparison.difference),
                comparison.unit,
                comparison.qualification,
            )
            for column, value in enumerate(values):
                self.saved_run_comparison_table.setItem(row_index, column, QTableWidgetItem(value))
        self.compatibility_label.setText(
            compatibility or "The runs were checked before comparison."
        )

    def show_notice(self, message: str, level: NoticeLevel | str = NoticeLevel.INFO) -> None:
        value = level.value if isinstance(level, NoticeLevel) else str(level)
        self.notice.show_message(message, value)

    def clear_notice(self) -> None:
        self.notice.clear()

    def show_error(self, message: str) -> None:
        self.show_notice(message, NoticeLevel.ERROR)
        self.status_pill.setText("Needs attention")

    def go_to_page(self, page: int | str) -> None:
        names = {
            "project": self.PAGE_HOME,
            "import": self.PAGE_IMPORT,
            "analyze": self.PAGE_ANALYZE,
            "results": self.PAGE_RESULTS,
        }
        index = names.get(page.lower(), -1) if isinstance(page, str) else int(page)
        if not 0 <= index < self.pages.count():
            raise ValueError(f"unknown workflow page: {page}")
        item = self.navigation.item(index)
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.navigation.setCurrentRow(index)

    def analysis_parameters(self) -> dict[str, Any]:
        return self.parameter_editor.parameters()

    def _apply_viewer_roi(self, name: str, value: dict[str, int]) -> None:
        fields = {
            "analysis": self.parameter_editor.analysis_roi,
            "background": self.parameter_editor.background_roi,
            "envelope": self.parameter_editor.envelope_roi,
        }
        field = fields.get(name)
        if field is not None:
            field.set_value(value)

    def _apply_viewer_polygon(self, name: str, points: list[list[float]]) -> None:
        self.parameter_editor.set_polygon(name, points)

    def set_plane(self, *args: Any, **kwargs: Any) -> None:
        self.viewer.set_plane(*args, **kwargs)

    def set_stack(self, *args: Any, **kwargs: Any) -> None:
        self.viewer.set_stack(*args, **kwargs)

    def set_orthogonal(self, *args: Any, **kwargs: Any) -> None:
        self.viewer.set_orthogonal(*args, **kwargs)

    def set_plane_count(self, count: int, *, current: int = 0) -> None:
        self.viewer.set_plane_count(count, current=current)

    def set_roi_overlays(self, parameters: dict[str, Any]) -> None:
        self.viewer.set_roi_overlays(
            {
                "analysis": parameters.get("analysis_roi_xywh_px"),
                "background": parameters.get("background_roi_xywh_px"),
                "envelope": parameters.get("envelope_roi_xywh_px"),
            }
        )
        self.viewer.set_polygon_overlays(
            {
                "analysis": parameters.get("analysis_polygon_xy_px"),
                "background": parameters.get("background_polygon_xy_px"),
                "envelope": parameters.get("envelope_polygon_xy_px"),
            }
        )

    # Testable/request APIs avoid opening native dialogs when a controller already has a path.
    def request_create_project(self, path: str | Path) -> None:
        self.createProjectRequested.emit(str(path))

    def request_open_project(self, path: str | Path) -> None:
        self.openProjectRequested.emit(str(path))

    def request_import_source(self, path: str | Path) -> None:
        self.set_source_path(path)
        self.sourceImportRequested.emit(str(path))

    def request_export_csv(self, path: str | Path) -> None:
        self.exportCsvRequested.emit(str(path))

    def request_export_json(self, path: str | Path) -> None:
        self.exportJsonRequested.emit(str(path))

    def request_export_png(self, path: str | Path) -> None:
        self.exportPngRequested.emit(str(path))

    # ---------- UI event handlers ----------

    def _change_page(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex(index)
        self.page_title.setText(("Project", "Import", "Analyze", "Results")[index])

    def _set_nav_enabled(self, index: int, enabled: bool) -> None:
        item = self.navigation.item(index)
        if item is None:
            return
        flags = item.flags()
        if enabled:
            item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
        else:
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)

    def _choose_create_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder for the new project")
        if path:
            self.createProjectRequested.emit(path)

    def _choose_open_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open a Plug Analyzer project")
        if path:
            self.openProjectRequested.emit(path)

    def _choose_source(self) -> None:
        start = str(self._source_path.parent) if self._source_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose microscope source",
            start,
            "Microscope images (*.tif *.tiff *.nd2);;TIFF images (*.tif *.tiff);;Nikon ND2 (*.nd2);;All files (*)",
        )
        if path:
            self.set_source_path(path)

    def _request_source_import(self) -> None:
        value = self.source_path_edit.text().strip()
        if not value:
            self.show_error("Choose a TIFF or ND2 source first.")
            return
        self.sourceImportRequested.emit(value)

    def _request_analysis(self) -> None:
        error = self.parameter_editor.validation_error()
        if error:
            self.show_notice(error, NoticeLevel.WARNING)
            return
        if not self._preflight_safe:
            self.show_error("Resource preflight has not passed; analysis was not started.")
            return
        self.clear_notice()
        parameters = self.parameter_editor.parameters()
        self.analyzeRequested.emit(parameters)

    def _choose_csv_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export results as CSV", "plug-analysis.csv", "CSV (*.csv)"
        )
        if path:
            self.exportCsvRequested.emit(path)

    def _choose_json_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export results as JSON", "plug-analysis.json", "JSON (*.json)"
        )
        if path:
            self.exportJsonRequested.emit(path)

    def _choose_png_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export result figure", "plug-analysis.png", "PNG image (*.png)"
        )
        if path:
            self.exportPngRequested.emit(path)

    def _copy_comparison_table(self) -> None:
        self._copy_table(self.saved_run_comparison_table, "Comparison table")

    def _copy_table(self, table: QTableWidget, label: str) -> None:
        rows = [
            "\t".join(
                table.horizontalHeaderItem(column).text() for column in range(table.columnCount())
            )
        ]
        for row in range(table.rowCount()):
            rows.append(
                "\t".join(
                    table.item(row, column).text() if table.item(row, column) else ""
                    for column in range(table.columnCount())
                )
            )
        QGuiApplication.clipboard().setText("\n".join(rows))
        self.show_notice(f"{label} copied as tab-separated text.", NoticeLevel.SUCCESS)

    def _request_reveal_storage(self) -> None:
        value = self.project_path_edit.text().strip()
        if value:
            self.revealStorageRequested.emit(value)

    def _request_sample_selection(self) -> None:
        identifier = self.sample_selector.currentData()
        if identifier:
            self.sampleSelectedRequested.emit(str(identifier))

    def _request_saved_run_comparison(self) -> None:
        left = self.left_run_selector.currentData()
        right = self.right_run_selector.currentData()
        if left and right:
            self.savedRunsCompareRequested.emit(str(left), str(right))

    def _navigate_to_chart_plane(self, z_index: int) -> None:
        self.go_to_page(self.PAGE_ANALYZE)
        self.planeRequested.emit(z_index)

    @staticmethod
    def _fill_table(table: QTableWidget, rows: Any) -> None:
        materialized = list(rows)
        table.setRowCount(len(materialized))
        for row, values in enumerate(materialized):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _format_metric_value(value: Any) -> str:
        if value is None:
            return "Not available"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def closeEvent(self, event: QCloseEvent) -> None:
        controller = getattr(self, "_application_controller", None)
        request_close = getattr(controller, "request_close", None)
        if callable(request_close):
            if not request_close():
                event.ignore()
                return
        else:
            self.closing.emit()
        super().closeEvent(event)


class AboutDialog(QDialog):
    """Reserved lightweight about dialog for packaged builds."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Plug Analyzer")
        layout = QVBoxLayout(self)
        title = QLabel("Plug Analyzer prototype")
        title.setProperty("class", "sectionTitle")
        text = QLabel(
            "Local deterministic analysis of fluorescence-defined plug formation in microscope "
            "Z-stacks. Research-use prototype; not a clinical or standalone functional test."
        )
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
