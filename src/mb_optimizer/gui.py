from __future__ import annotations

import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QElapsedTimer,
    QObject,
    QSettings,
    QStandardPaths,
    Qt,
    QThread,
    QUrl,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .endpoints import (
    CLOUDFLARE_SPEED_URL,
    DEFAULT_TEST_URL,
    TEST_URL_PRESETS,
)
from .exporter import timestamped_result_path, write_results_csv
from .models import AggregatedResult, OptimizationOptions
from .optimizer import OptimizationService
from .runner import CfstCancelled
from .updater import UpdateClient, UpdateInfo


class NumericItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            return float(left) < float(right)
        return super().__lt__(other)


class OptimizationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    status_changed = Signal(str, int)
    log_added = Signal(str)
    endpoint_selected = Signal(str)

    def __init__(self, options: OptimizationOptions) -> None:
        super().__init__()
        self.service = OptimizationService(
            status=self.status_changed.emit,
            log=self.log_added.emit,
            endpoint_selected=self.endpoint_selected.emit,
        )
        self.options = options

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.service.optimize(self.options))
        except CfstCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - report worker failures to the UI
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.service.stop()


class UpdateCheckWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(UpdateClient().check())
        except Exception as exc:  # noqa: BLE001 - report worker failures to the UI
            self.failed.emit(str(exc))


class UpdateInstallWorker(QObject):
    finished = Signal()
    failed = Signal(str)
    progress_changed = Signal(int)

    def __init__(self, info: UpdateInfo) -> None:
        super().__init__()
        self.info = info

    @Slot()
    def run(self) -> None:
        try:

            def progress(downloaded: int, total: int) -> None:
                self.progress_changed.emit(
                    int(downloaded * 100 / total) if total else 0
                )

            UpdateClient().install(self.info, progress)
            self.finished.emit()
        except Exception as exc:  # noqa: BLE001 - report worker failures to the UI
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings()
        self.results: list[AggregatedResult] = []
        self.custom_ip_file: Path | None = None
        self.optimize_thread: QThread | None = None
        self.optimize_worker: OptimizationWorker | None = None
        self.update_thread: QThread | None = None
        self.update_worker: QObject | None = None
        self.pending_update_info: UpdateInfo | None = None
        self.latest_result_path: Path | None = None
        self.network_mode = "用户确认直连"
        self.current_status_message = "就绪"
        self.run_clock = QElapsedTimer()
        self.progress_update_clock = QElapsedTimer()
        self.elapsed_tick = QTimer(self)
        self.elapsed_tick.setInterval(1000)
        self.elapsed_tick.timeout.connect(self._refresh_elapsed_status)
        self.log_expanded = False
        self.previous_splitter_sizes = [500, 180]

        self.setWindowTitle(f"MB CF Optimizer {__version__}")
        self.setMinimumSize(880, 680)
        self.resize(934, 780)
        self._build_ui()
        self._apply_style()
        self._load_settings()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("MB CF Optimizer")
        title.setObjectName("title")
        version = QLabel(f"本地 Cloudflare IP 优选  ·  v{__version__}")
        version.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(version)
        header.addLayout(title_box)
        header.addStretch()
        self.update_button = QPushButton("检查更新")
        self.update_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.update_button.setToolTip("从 GitHub Releases 检查应用更新")
        self.update_button.clicked.connect(self._check_update)
        header.addWidget(self.update_button)
        root.addLayout(header)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(12)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 2)

        form.addWidget(QLabel("网络"), 0, 0)
        network_box = QHBoxLayout()
        network_box.setSpacing(0)
        self.ipv4_button = QPushButton("IPv4")
        self.ipv6_button = QPushButton("IPv6")
        for button in (self.ipv4_button, self.ipv6_button):
            button.setCheckable(True)
            button.setObjectName("segment")
            button.setMinimumWidth(76)
        self.ipv4_button.setChecked(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.ipv4_button)
        group.addButton(self.ipv6_button)
        network_box.addWidget(self.ipv4_button)
        network_box.addWidget(self.ipv6_button)
        network_box.addStretch()
        form.addLayout(network_box, 0, 1)

        form.addWidget(QLabel("端口"), 0, 2)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.port_input.setValue(443)
        form.addWidget(self.port_input, 0, 3)

        form.addWidget(QLabel("测速地址"), 1, 0)
        self.url_input = QComboBox()
        self.url_input.setEditable(True)
        self.url_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for label, url in TEST_URL_PRESETS:
            self.url_input.addItem(label, url)
        self.url_input.setEditText(DEFAULT_TEST_URL)
        self.url_input.lineEdit().setClearButtonEnabled(False)
        self.url_input.activated.connect(
            lambda index: self.url_input.setEditText(self.url_input.itemData(index))
        )
        form.addWidget(self.url_input, 1, 1, 1, 3)

        form.addWidget(QLabel("候选 IP"), 2, 0)
        source_box = QHBoxLayout()
        self.source_input = QLineEdit("Cloudflare 官方网段（自动更新）")
        self.source_input.setReadOnly(True)
        self.browse_button = QPushButton()
        self.browse_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.browse_button.setToolTip("选择自定义 IP 或 CIDR 文本文件")
        self.browse_button.clicked.connect(self._browse_ip_file)
        self.clear_source_button = QPushButton()
        self.clear_source_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self.clear_source_button.setToolTip("恢复使用自动更新的官方网段")
        self.clear_source_button.setEnabled(False)
        self.clear_source_button.clicked.connect(self._clear_ip_file)
        source_box.addWidget(self.source_input)
        source_box.addWidget(self.browse_button)
        source_box.addWidget(self.clear_source_button)
        form.addLayout(source_box, 2, 1, 1, 3)
        panel_layout.addLayout(form)

        self.filter_toggle = QToolButton()
        self.filter_toggle.setText("筛选设置")
        self.filter_toggle.setCheckable(True)
        self.filter_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.filter_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.filter_toggle.toggled.connect(self._toggle_filters)
        panel_layout.addWidget(self.filter_toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        self.filter_frame = QFrame()
        filter_layout = QGridLayout(self.filter_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setHorizontalSpacing(12)
        filter_layout.addWidget(QLabel("延迟上限"), 0, 0)
        self.latency_input = QSpinBox()
        self.latency_input.setRange(50, 2000)
        self.latency_input.setSuffix(" ms")
        self.latency_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.latency_input.setValue(300)
        filter_layout.addWidget(self.latency_input, 0, 1)
        filter_layout.addWidget(QLabel("丢包上限"), 0, 2)
        self.loss_input = QDoubleSpinBox()
        self.loss_input.setRange(0, 100)
        self.loss_input.setSuffix(" %")
        self.loss_input.setDecimals(0)
        self.loss_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.loss_input.setValue(25)
        filter_layout.addWidget(self.loss_input, 0, 3)
        filter_layout.addWidget(QLabel("广筛数量"), 0, 4)
        self.broad_count_input = QSpinBox()
        self.broad_count_input.setRange(100, 5000)
        self.broad_count_input.setSingleStep(100)
        self.broad_count_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.broad_count_input.setValue(800)
        filter_layout.addWidget(self.broad_count_input, 0, 5)
        filter_layout.setColumnStretch(6, 1)
        self.filter_frame.setVisible(False)
        panel_layout.addWidget(self.filter_frame)
        root.addWidget(panel)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始优选")
        self.start_button.setObjectName("primary")
        self.start_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.start_button.clicked.connect(self._start_optimization)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("danger")
        self.stop_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_optimization)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        self.open_result_button = QPushButton("打开结果文件夹")
        self.open_result_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.open_result_button.setEnabled(False)
        self.open_result_button.clicked.connect(self._open_result_folder)
        actions.addWidget(self.open_result_button)
        self.export_button = QPushButton("另存为")
        self.export_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_csv)
        actions.addWidget(self.export_button)
        root.addLayout(actions)

        status_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(240)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        status_row.addWidget(self.progress)
        root.addLayout(status_row)

        self.summary = QFrame()
        self.summary.setObjectName("summary")
        summary_layout = QHBoxLayout(self.summary)
        summary_layout.setContentsMargins(16, 12, 12, 12)
        summary_caption = QLabel("首选")
        summary_caption.setObjectName("summaryCaption")
        self.best_label = QLabel()
        self.best_label.setObjectName("bestIp")
        self.best_detail = QLabel()
        self.best_detail.setObjectName("muted")
        self.copy_best_button = QPushButton("复制")
        self.copy_best_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        self.copy_best_button.clicked.connect(self._copy_best)
        summary_layout.addWidget(summary_caption)
        summary_layout.addWidget(self.best_label)
        summary_layout.addWidget(self.best_detail)
        summary_layout.addStretch()
        summary_layout.addWidget(self.copy_best_button)
        self.summary.setVisible(False)
        root.addWidget(self.summary)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setChildrenCollapsible(True)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["推荐", "IP", "地区", "成功率", "丢包", "速度 MB/s", "延迟 ms", "波动 ms"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._copy_selected)
        self.content_splitter.addWidget(self.table)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_header = QHBoxLayout()
        self.log_toggle = QToolButton()
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.toggled.connect(self._toggle_log)
        self.copy_log_button = QPushButton("复制日志")
        self.copy_log_button.setToolTip("复制全部诊断日志")
        self.copy_log_button.clicked.connect(self._copy_log)
        self.save_log_button = QPushButton("保存日志")
        self.save_log_button.setToolTip("保存诊断日志文件")
        self.save_log_button.clicked.connect(self._save_log)
        self.expand_log_button = QPushButton()
        self.expand_log_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton)
        )
        self.expand_log_button.setToolTip("放大或恢复日志区域")
        self.expand_log_button.setEnabled(False)
        self.expand_log_button.clicked.connect(self._toggle_log_expanded)
        log_header.addWidget(self.log_toggle)
        log_header.addStretch()
        log_header.addWidget(self.copy_log_button)
        log_header.addWidget(self.save_log_button)
        log_header.addWidget(self.expand_log_button)
        log_layout.addLayout(log_header)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(2000)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.setMinimumHeight(100)
        self.log_output.setVisible(False)
        log_layout.addWidget(self.log_output, 1)
        self.content_splitter.addWidget(log_panel)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([520, 36])
        root.addWidget(self.content_splitter, 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#central { background: #c5cbd0; }
            QWidget { color: #18212b; }
            QLabel { background: transparent; }
            QDialog, QMessageBox { background: #cbd1d5; color: #18212b; }
            QDialog QLabel, QMessageBox QLabel { background: transparent; color: #18212b; }
            QLabel#title { font-size: 22px; font-weight: 700; color: #111827; }
            QLabel#muted { color: #53606c; }
            QLabel#status { color: #344054; font-weight: 600; }
            QFrame#panel { background: #d4dade; border: 1px solid #aab5ba; border-radius: 6px; }
            QFrame#summary { background: #d8e5e1; border: 1px solid #80b7a6; border-radius: 6px; }
            QLabel#summaryCaption { color: #08785e; font-weight: 700; }
            QLabel#bestIp { font-size: 16px; font-weight: 700; color: #12382f; }
            QPushButton, QToolButton { min-height: 32px; padding: 0 12px; background: #dce1e4; border: 1px solid #9eabb1; border-radius: 5px; }
            QPushButton:hover, QToolButton:hover { background: #d1d8dc; border-color: #778b94; }
            QPushButton:disabled { color: #7f8992; background: #cfd5d8; border-color: #b9c2c6; }
            QPushButton#primary { color: #ffffff; background: #0f766e; border-color: #0f766e; font-weight: 700; min-width: 112px; }
            QPushButton#primary:hover { background: #0b665f; }
            QPushButton#danger { color: #8c2f2f; background: #eadede; border-color: #cfa8a8; min-width: 82px; }
            QPushButton#segment { border-radius: 0; min-height: 30px; }
            QPushButton#segment:first { border-top-left-radius: 5px; border-bottom-left-radius: 5px; }
            QPushButton#segment:checked { color: #ffffff; background: #344054; border-color: #344054; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 32px; background: #e3e7e9; border: 1px solid #9eabb1; border-radius: 4px; padding: 0 8px; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2f80a3; }
            QComboBox QAbstractItemView { background: #e3e7e9; border: 1px solid #9eabb1; selection-background-color: #c5d9de; }
            QProgressBar { height: 8px; background: #dfe5eb; border: 0; border-radius: 4px; }
            QProgressBar::chunk { background: #159a80; border-radius: 4px; }
            QTableWidget { background: #dfe4e6; alternate-background-color: #d4dade; border: 1px solid #aab5ba; border-radius: 4px; gridline-color: #bec8cc; selection-background-color: #bad2d8; selection-color: #18212b; }
            QHeaderView::section { background: #cbd3d7; color: #344054; padding: 8px; border: 0; border-right: 1px solid #aab5ba; font-weight: 600; }
            QSplitter::handle { background: #c5d1d5; height: 5px; }
            QPlainTextEdit { background: #151b22; color: #d6dde5; border: 1px solid #303944; border-radius: 4px; padding: 8px; font-family: Consolas; }
            """
        )

    def _load_settings(self) -> None:
        schema = self.settings.value("settings_schema", 0, int)
        self.port_input.setValue(self.settings.value("port", 443, int))
        if schema >= 2:
            saved_url = self.settings.value("test_url", DEFAULT_TEST_URL, str)
            if schema < 4 and saved_url == CLOUDFLARE_SPEED_URL:
                saved_url = DEFAULT_TEST_URL
            self.url_input.setEditText(saved_url)
            latency = self.settings.value("max_latency", 300, int)
            loss = self.settings.value("max_loss_percent", 25, float)
            if schema < 4 and latency == 1000:
                latency = 300
            if schema < 4 and loss == 100:
                loss = 25
            self.latency_input.setValue(latency)
            self.loss_input.setValue(loss)
            self.broad_count_input.setValue(
                self.settings.value("broad_candidate_count", 800, int)
            )
        if self.settings.value("ipv6", False, bool):
            self.ipv6_button.setChecked(True)

    def _save_settings(self) -> None:
        self.settings.setValue("settings_schema", 4)
        self.settings.setValue("test_url", self.url_input.currentText().strip())
        self.settings.setValue("port", self.port_input.value())
        self.settings.setValue("max_latency", self.latency_input.value())
        self.settings.setValue("max_loss_percent", self.loss_input.value())
        self.settings.setValue("broad_candidate_count", self.broad_count_input.value())
        self.settings.setValue("ipv6", self.ipv6_button.isChecked())
        if self.log_output.isVisible():
            height = (
                self.previous_splitter_sizes[1]
                if self.log_expanded
                else self.content_splitter.sizes()[1]
            )
            self.settings.setValue("log_height", height)

    def _toggle_filters(self, visible: bool) -> None:
        self.filter_frame.setVisible(visible)
        self.filter_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )

    def _toggle_log(self, visible: bool) -> None:
        self.log_output.setVisible(visible)
        self.expand_log_button.setEnabled(visible)
        self.log_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )
        if visible:
            height = self.settings.value("log_height", 180, int)
            self.content_splitter.setSizes([max(240, self.height() - height), height])
        else:
            self.log_expanded = False
            self.content_splitter.setSizes([1, 36])

    def _toggle_log_expanded(self) -> None:
        if not self.log_output.isVisible():
            return
        if self.log_expanded:
            self.content_splitter.setSizes(self.previous_splitter_sizes)
            icon = QStyle.StandardPixmap.SP_TitleBarMaxButton
        else:
            self.previous_splitter_sizes = self.content_splitter.sizes()
            self.content_splitter.setSizes([0, 1])
            icon = QStyle.StandardPixmap.SP_TitleBarNormalButton
        self.log_expanded = not self.log_expanded
        self.expand_log_button.setIcon(self.style().standardIcon(icon))

    def _browse_ip_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "选择候选 IP 文件", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if filename:
            self.custom_ip_file = Path(filename)
            self.source_input.setText(filename)
            self.clear_source_button.setEnabled(True)

    def _clear_ip_file(self) -> None:
        self.custom_ip_file = None
        self.source_input.setText("Cloudflare 官方网段（自动更新）")
        self.clear_source_button.setEnabled(False)

    def _options(self) -> OptimizationOptions:
        return OptimizationOptions(
            ipv6=self.ipv6_button.isChecked(),
            port=self.port_input.value(),
            test_url=self.url_input.currentText().strip(),
            custom_ip_file=self.custom_ip_file,
            broad_candidate_count=self.broad_count_input.value(),
            max_latency_ms=self.latency_input.value(),
            max_loss_rate=self.loss_input.value() / 100,
        )

    def _start_optimization(self) -> None:
        if self.optimize_thread:
            return
        answer = QMessageBox.question(
            self,
            "确认直连网络",
            "请先关闭 OpenClash、PassWall、TUN 等透明代理，并在本轮测速中保持网络路由不变。\n\n确认当前电脑已直连后继续。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        options = self._options()
        try:
            options.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "设置无效", str(exc))
            return

        self._save_settings()
        self.results = []
        self.latest_result_path = None
        self.open_result_button.setEnabled(False)
        self.table.setRowCount(0)
        self.summary.setVisible(False)
        self.log_output.clear()
        if not self.log_toggle.isChecked():
            self.log_toggle.setChecked(True)
        self.progress.setValue(0)
        self._set_running(True)

        thread = QThread(self)
        worker = OptimizationWorker(options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status_changed.connect(self._set_status)
        worker.log_added.connect(self.log_output.appendPlainText)
        worker.endpoint_selected.connect(self._endpoint_selected)
        worker.finished.connect(self._optimization_finished)
        worker.failed.connect(self._optimization_failed)
        worker.cancelled.connect(self._optimization_cancelled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._optimization_thread_finished)
        self.optimize_thread = thread
        self.optimize_worker = worker
        thread.start()

    def _stop_optimization(self) -> None:
        if self.optimize_worker:
            self.current_status_message = "正在停止"
            self._refresh_elapsed_status()
            self.stop_button.setEnabled(False)
            self.optimize_worker.cancel()

    @Slot(str, int)
    def _set_status(self, message: str, progress: int) -> None:
        self.current_status_message = message
        self._refresh_elapsed_status()
        if progress < 0:
            self.progress_update_clock.invalidate()
            self.progress.setRange(0, 0)
        else:
            self.progress_update_clock.start()
            if self.progress.maximum() == 0:
                self.progress.setRange(0, 100)
            self.progress.setValue(progress)

    def _refresh_elapsed_status(self) -> None:
        if self.elapsed_tick.isActive() and self.run_clock.isValid():
            seconds = self.run_clock.elapsed() // 1000
            self.status_label.setText(
                f"{self.current_status_message} · 已用 {seconds // 60:02d}:{seconds % 60:02d}"
            )
            if (
                self.progress.maximum() != 0
                and self.progress_update_clock.isValid()
                and self.progress_update_clock.elapsed() >= 8000
            ):
                self.progress_update_clock.invalidate()
                self.progress.setRange(0, 0)
        else:
            self.status_label.setText(self.current_status_message)

    @Slot(str)
    def _endpoint_selected(self, url: str) -> None:
        self.url_input.setEditText(url)
        self.settings.setValue("test_url", url)

    @Slot(object)
    def _optimization_finished(self, results: object) -> None:
        self.results = list(results)
        self._populate_results()
        export_error: str | None = None
        try:
            desktop = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DesktopLocation
            )
            destination = timestamped_result_path(Path(desktop or Path.home()))
            write_results_csv(
                destination,
                self.results,
                self.network_mode,
                self.url_input.currentText().strip(),
            )
            self.latest_result_path = destination
            self.open_result_button.setEnabled(True)
            elapsed = self.run_clock.elapsed() // 1000
            self.log_output.appendPlainText(
                f"[{elapsed // 60:02d}:{elapsed % 60:02d}] [INFO] 最终结果已保存：{destination}"
            )
            self.current_status_message = f"优选完成 · 已保存 {destination.name}"
        except OSError as exc:
            export_error = str(exc)
            self.current_status_message = "优选完成 · 自动保存失败"
        self._set_running(False)
        self._refresh_elapsed_status()
        if export_error:
            QMessageBox.warning(
                self,
                "自动保存失败",
                f"优选已经完成，但无法自动保存到桌面：\n{export_error}\n\n请使用“另存为”。",
            )

    @Slot(str)
    def _optimization_failed(self, message: str) -> None:
        self.current_status_message = "优选失败"
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_running(False)
        self._refresh_elapsed_status()
        QMessageBox.critical(self, "优选失败", message)

    @Slot()
    def _optimization_cancelled(self) -> None:
        self.current_status_message = "已停止"
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_running(False)
        self._refresh_elapsed_status()

    @Slot()
    def _optimization_thread_finished(self) -> None:
        if self.optimize_thread:
            self.optimize_thread.deleteLater()
        self.optimize_thread = None
        self.optimize_worker = None

    def _set_running(self, running: bool) -> None:
        if running:
            self.current_status_message = "准备开始"
            self.run_clock.start()
            self.progress_update_clock.invalidate()
            self.elapsed_tick.start()
            self._refresh_elapsed_status()
        else:
            self.elapsed_tick.stop()
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.update_button.setEnabled(not running)
        self.export_button.setEnabled(bool(self.results) and not running)
        for widget in (
            self.ipv4_button,
            self.ipv6_button,
            self.port_input,
            self.url_input,
            self.browse_button,
            self.clear_source_button,
            self.latency_input,
            self.loss_input,
            self.broad_count_input,
        ):
            widget.setEnabled(not running)

    def _populate_results(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for row, result in enumerate(self.results):
            recommendation = "首选" if row == 0 else f"备用 {row}" if row <= 3 else ""
            values: list[tuple[str, float | None]] = [
                (recommendation, float(row)),
                (result.ip, None),
                (result.region, None),
                (f"{result.success_rate:.0%}", result.success_rate),
                (f"{result.median_loss_rate:.0%}", result.median_loss_rate),
                (f"{result.median_speed_mb_s:.2f}", result.median_speed_mb_s),
                (f"{result.median_latency_ms:.1f}", result.median_latency_ms),
                (f"{result.latency_jitter_ms:.1f}", result.latency_jitter_ms),
            ]
            for column, (text, numeric) in enumerate(values):
                item = (
                    NumericItem(text) if numeric is not None else QTableWidgetItem(text)
                )
                if numeric is not None:
                    item.setData(Qt.ItemDataRole.UserRole, numeric)
                if column == 0 and row == 0:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        best = self.results[0]
        self.best_label.setText(best.ip)
        self.best_detail.setText(
            f"{best.median_speed_mb_s:.2f} MB/s  ·  {best.median_latency_ms:.1f} ms  ·  成功率 {best.success_rate:.0%}  ·  {self.network_mode}"
        )
        self.summary.setVisible(True)
        self.export_button.setEnabled(True)

    def _copy_best(self) -> None:
        if self.results:
            QGuiApplication.clipboard().setText(self.results[0].ip)
            self.status_label.setText("已复制首选 IP")

    def _copy_selected(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 1) if row >= 0 else None
        if item:
            QGuiApplication.clipboard().setText(item.text())
            self.status_label.setText("已复制 IP")

    def _export_csv(self) -> None:
        if not self.results:
            return
        initial = self.latest_result_path.name if self.latest_result_path else "mb-cf-results.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self, "另存优选结果", initial, "CSV 文件 (*.csv)"
        )
        if not filename:
            return
        try:
            write_results_csv(
                Path(filename),
                self.results,
                self.network_mode,
                self.url_input.currentText().strip(),
            )
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.status_label.setText("结果已另存")

    def _open_result_folder(self) -> None:
        if self.latest_result_path:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.latest_result_path.parent))
            )

    def _copy_log(self) -> None:
        QGuiApplication.clipboard().setText(self.log_output.toPlainText())
        self.status_label.setText("已复制诊断日志")

    def _save_log(self) -> None:
        default_name = f"MB-CF-Optimizer-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.log"
        filename, _ = QFileDialog.getSaveFileName(
            self, "保存诊断日志", default_name, "日志文件 (*.log);;文本文件 (*.txt)"
        )
        if not filename:
            return
        try:
            Path(filename).write_text(self.log_output.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.status_label.setText("诊断日志已保存")

    def _check_update(self) -> None:
        if self.update_thread:
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("正在检查")
        thread = QThread(self)
        worker = UpdateCheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._update_checked)
        worker.failed.connect(self._update_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._update_thread_finished)
        self.update_thread = thread
        self.update_worker = worker
        thread.start()

    @Slot(object)
    def _update_checked(self, info: object) -> None:
        if info is None:
            QMessageBox.information(self, "检查更新", "当前已经是最新版本。")
            return
        update = info
        notes = update.notes[:600] if update.notes else "该版本未提供更新说明。"
        answer = QMessageBox.question(
            self,
            "发现新版本",
            f"发现 v{update.version}。\n\n{notes}\n\n现在更新吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if (
            not getattr(sys, "frozen", False)
            or not update.asset_url
            or not update.checksum_url
        ):
            webbrowser.open(update.release_url)
            QMessageBox.information(
                self, "打开发布页", "当前运行方式不能自动替换程序，已打开发布页面。"
            )
            return
        self.pending_update_info = update

    def _start_update_install(self, info: UpdateInfo) -> None:
        self.update_button.setText("下载更新 0%")
        thread = QThread(self)
        worker = UpdateInstallWorker(info)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(
            lambda value: self.update_button.setText(f"下载更新 {value}%")
        )
        worker.finished.connect(self._update_installed)
        worker.failed.connect(self._update_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._update_thread_finished)
        self.update_thread = thread
        self.update_worker = worker
        thread.start()

    @Slot()
    def _update_installed(self) -> None:
        QMessageBox.information(
            self, "更新已下载", "程序将退出、完成替换并自动重新启动。"
        )
        if self.update_thread:
            self.update_thread.quit()
            self.update_thread.wait(3000)
        QApplication.quit()

    @Slot(str)
    def _update_failed(self, message: str) -> None:
        QMessageBox.warning(self, "更新失败", message)

    @Slot()
    def _update_thread_finished(self) -> None:
        if self.update_thread:
            self.update_thread.deleteLater()
        self.update_thread = None
        self.update_worker = None
        if self.pending_update_info:
            info = self.pending_update_info
            self.pending_update_info = None
            QTimer.singleShot(0, lambda: self._start_update_install(info))
            return
        self.update_button.setText("检查更新")
        self.update_button.setEnabled(self.optimize_thread is None)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.optimize_worker:
            answer = QMessageBox.question(
                self,
                "停止优选",
                "测速仍在运行，停止并退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.optimize_worker.cancel()
            if self.optimize_thread:
                self.optimize_thread.quit()
                if not self.optimize_thread.wait(5000):
                    self.status_label.setText("正在清理测速进程，请稍后退出")
                    event.ignore()
                    return
        self._save_settings()
        event.accept()
