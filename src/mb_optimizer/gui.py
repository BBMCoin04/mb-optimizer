from __future__ import annotations

import csv
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
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
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
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

    def __init__(self, options: OptimizationOptions) -> None:
        super().__init__()
        self.service = OptimizationService(
            status=self.status_changed.emit,
            log=self.log_added.emit,
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

        self.setWindowTitle(f"MB CF Optimizer {__version__}")
        self.setMinimumSize(940, 680)
        self.resize(1120, 780)
        self._build_ui()
        self._apply_style()
        self._load_settings()

    def _build_ui(self) -> None:
        central = QWidget()
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
        self.port_input.setValue(443)
        form.addWidget(self.port_input, 0, 3)

        form.addWidget(QLabel("测速地址"), 1, 0)
        self.url_input = QLineEdit("https://cf.xiu2.xyz/url")
        self.url_input.setClearButtonEnabled(True)
        form.addWidget(self.url_input, 1, 1, 1, 3)

        form.addWidget(QLabel("候选 IP"), 2, 0)
        source_box = QHBoxLayout()
        self.source_input = QLineEdit("使用 CFST 内置网段")
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
        self.clear_source_button.setToolTip("恢复使用内置网段")
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
        self.latency_input.setValue(300)
        filter_layout.addWidget(self.latency_input, 0, 1)
        filter_layout.addWidget(QLabel("丢包上限"), 0, 2)
        self.loss_input = QDoubleSpinBox()
        self.loss_input.setRange(0, 100)
        self.loss_input.setSuffix(" %")
        self.loss_input.setDecimals(0)
        self.loss_input.setValue(20)
        filter_layout.addWidget(self.loss_input, 0, 3)
        filter_layout.addWidget(QLabel("复测候选"), 0, 4)
        self.candidate_input = QSpinBox()
        self.candidate_input.setRange(3, 30)
        self.candidate_input.setValue(10)
        filter_layout.addWidget(self.candidate_input, 0, 5)
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
        self.export_button = QPushButton("导出 CSV")
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
        root.addWidget(self.table, 1)

        self.log_toggle = QToolButton()
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.toggled.connect(self._toggle_log)
        root.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        self.log_output.setFixedHeight(130)
        self.log_output.setVisible(False)
        root.addWidget(self.log_output)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f6f8; color: #18212b; }
            QLabel#title { font-size: 22px; font-weight: 700; color: #111827; }
            QLabel#muted { color: #667085; }
            QLabel#status { color: #344054; font-weight: 600; }
            QFrame#panel { background: #ffffff; border: 1px solid #d8dee6; border-radius: 6px; }
            QFrame#summary { background: #eef8f4; border: 1px solid #9bd5c3; border-radius: 6px; }
            QLabel#summaryCaption { color: #08785e; font-weight: 700; }
            QLabel#bestIp { font-size: 16px; font-weight: 700; color: #12382f; }
            QPushButton, QToolButton { min-height: 32px; padding: 0 12px; background: #ffffff; border: 1px solid #cbd3dc; border-radius: 5px; }
            QPushButton:hover, QToolButton:hover { background: #f8fafc; border-color: #98a5b3; }
            QPushButton:disabled { color: #98a2b3; background: #eef1f4; border-color: #d8dee6; }
            QPushButton#primary { color: #ffffff; background: #0f766e; border-color: #0f766e; font-weight: 700; min-width: 112px; }
            QPushButton#primary:hover { background: #0b665f; }
            QPushButton#danger { color: #9b2c2c; background: #fff7f7; border-color: #e3b5b5; min-width: 82px; }
            QPushButton#segment { border-radius: 0; min-height: 30px; }
            QPushButton#segment:first { border-top-left-radius: 5px; border-bottom-left-radius: 5px; }
            QPushButton#segment:checked { color: #ffffff; background: #344054; border-color: #344054; }
            QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 32px; background: #ffffff; border: 1px solid #cbd3dc; border-radius: 4px; padding: 0 8px; }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2f80a3; }
            QProgressBar { height: 8px; background: #dfe5eb; border: 0; border-radius: 4px; }
            QProgressBar::chunk { background: #159a80; border-radius: 4px; }
            QTableWidget { background: #ffffff; alternate-background-color: #f8fafb; border: 1px solid #d8dee6; border-radius: 4px; gridline-color: #e6eaf0; selection-background-color: #dcecf3; selection-color: #18212b; }
            QHeaderView::section { background: #eef1f4; color: #344054; padding: 8px; border: 0; border-right: 1px solid #d8dee6; font-weight: 600; }
            QPlainTextEdit { background: #151b22; color: #d6dde5; border: 1px solid #303944; border-radius: 4px; padding: 8px; font-family: Consolas; }
            """
        )

    def _load_settings(self) -> None:
        self.url_input.setText(
            self.settings.value("test_url", self.url_input.text(), str)
        )
        self.port_input.setValue(self.settings.value("port", 443, int))
        self.latency_input.setValue(self.settings.value("max_latency", 300, int))
        self.loss_input.setValue(self.settings.value("max_loss_percent", 20, float))
        self.candidate_input.setValue(self.settings.value("candidate_count", 10, int))
        if self.settings.value("ipv6", False, bool):
            self.ipv6_button.setChecked(True)

    def _save_settings(self) -> None:
        self.settings.setValue("test_url", self.url_input.text().strip())
        self.settings.setValue("port", self.port_input.value())
        self.settings.setValue("max_latency", self.latency_input.value())
        self.settings.setValue("max_loss_percent", self.loss_input.value())
        self.settings.setValue("candidate_count", self.candidate_input.value())
        self.settings.setValue("ipv6", self.ipv6_button.isChecked())

    def _toggle_filters(self, visible: bool) -> None:
        self.filter_frame.setVisible(visible)
        self.filter_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )

    def _toggle_log(self, visible: bool) -> None:
        self.log_output.setVisible(visible)
        self.log_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )

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
        self.source_input.setText("使用 CFST 内置网段")
        self.clear_source_button.setEnabled(False)

    def _options(self) -> OptimizationOptions:
        return OptimizationOptions(
            ipv6=self.ipv6_button.isChecked(),
            port=self.port_input.value(),
            test_url=self.url_input.text().strip(),
            custom_ip_file=self.custom_ip_file,
            candidate_count=self.candidate_input.value(),
            max_latency_ms=self.latency_input.value(),
            max_loss_rate=self.loss_input.value() / 100,
        )

    def _start_optimization(self) -> None:
        if self.optimize_thread:
            return
        options = self._options()
        try:
            options.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "设置无效", str(exc))
            return

        self._save_settings()
        self.results = []
        self.table.setRowCount(0)
        self.summary.setVisible(False)
        self.log_output.clear()
        self.progress.setValue(0)
        self._set_running(True)

        thread = QThread(self)
        worker = OptimizationWorker(options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status_changed.connect(self._set_status)
        worker.log_added.connect(self.log_output.appendPlainText)
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
            self.status_label.setText("正在停止")
            self.stop_button.setEnabled(False)
            self.optimize_worker.cancel()

    @Slot(str, int)
    def _set_status(self, message: str, progress: int) -> None:
        self.status_label.setText(message)
        self.progress.setValue(progress)

    @Slot(object)
    def _optimization_finished(self, results: object) -> None:
        self.results = list(results)
        self._populate_results()
        self._set_running(False)

    @Slot(str)
    def _optimization_failed(self, message: str) -> None:
        self.status_label.setText("优选失败")
        self._set_running(False)
        QMessageBox.critical(self, "优选失败", message)

    @Slot()
    def _optimization_cancelled(self) -> None:
        self.status_label.setText("已停止")
        self.progress.setValue(0)
        self._set_running(False)

    @Slot()
    def _optimization_thread_finished(self) -> None:
        if self.optimize_thread:
            self.optimize_thread.deleteLater()
        self.optimize_thread = None
        self.optimize_worker = None

    def _set_running(self, running: bool) -> None:
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
            self.candidate_input,
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
            f"{best.median_speed_mb_s:.2f} MB/s  ·  {best.median_latency_ms:.1f} ms  ·  成功率 {best.success_rate:.0%}"
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
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出优选结果", "mb-cf-results.csv", "CSV 文件 (*.csv)"
        )
        if not filename:
            return
        with Path(filename).open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(
                [
                    "推荐",
                    "IP",
                    "地区",
                    "成功率",
                    "丢包率",
                    "速度(MB/s)",
                    "延迟(ms)",
                    "波动(ms)",
                ]
            )
            for index, result in enumerate(self.results):
                recommendation = (
                    "首选" if index == 0 else f"备用 {index}" if index <= 3 else ""
                )
                writer.writerow(
                    [
                        recommendation,
                        result.ip,
                        result.region,
                        f"{result.success_rate:.0%}",
                        f"{result.median_loss_rate:.0%}",
                        f"{result.median_speed_mb_s:.2f}",
                        f"{result.median_latency_ms:.1f}",
                        f"{result.latency_jitter_ms:.1f}",
                    ]
                )
        self.status_label.setText("结果已导出")

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
