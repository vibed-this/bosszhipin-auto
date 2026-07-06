"""数据管理窗口 — 投递记录 + 对话记录 CRUD。"""
from __future__ import annotations

import csv
import os
from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bzauto.config import get_config
from bzauto.models import classify_msg_type
from bzauto.storage import Storage


class DataWindow(QWidget):
    """数据管理窗口，包含投递记录和对话记录两个 tab。"""

    def __init__(self, storage: Storage | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据管理")
        self.setMinimumSize(900, 600)
        self._storage = storage or Storage()
        self._setup_ui()
        self.refresh_all()
        self.showMaximized()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._jobs_tab = QWidget()
        self._tabs.addTab(self._jobs_tab, "投递记录")
        self._build_jobs_tab()

        self._conv_tab = QWidget()
        self._tabs.addTab(self._conv_tab, "对话记录")
        self._build_conv_tab()

    def _build_jobs_tab(self):
        layout = QVBoxLayout(self._jobs_tab)

        toolbar = QHBoxLayout()
        self._jobs_search = QLineEdit()
        self._jobs_search.setPlaceholderText("搜索职位/公司...")
        self._jobs_search.textChanged.connect(lambda: self._refresh_jobs())
        self._jobs_status = QComboBox()
        self._jobs_status.addItems(["全部", "已沟通", "HR已读", "HR已回复", "已邀面试", "已拒绝", "已结束"])
        self._jobs_status.currentTextChanged.connect(lambda: self._refresh_jobs())
        self._btn_export = QPushButton("导出 CSV")
        self._btn_export.clicked.connect(self._export_jobs_csv)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh_jobs)
        toolbar.addWidget(self._jobs_search)
        toolbar.addWidget(self._jobs_status)
        toolbar.addWidget(self._btn_export)
        toolbar.addWidget(self._btn_refresh)
        layout.addLayout(toolbar)

        self._jobs_table = QTableWidget(0, 7)
        self._jobs_table.setHorizontalHeaderLabels(["职位名", "公司", "薪资", "状态", "账号", "投递时间", "备注"])
        header = self._jobs_table.horizontalHeader()
        widths = [180, 160, 80, 80, 80, 160, 120]
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self._jobs_table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        self._jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._jobs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._jobs_table.customContextMenuRequested.connect(self._jobs_context_menu)
        self._jobs_table.setSortingEnabled(True)
        self._jobs_table.viewport().installEventFilter(self)
        layout.addWidget(self._jobs_table)

        self._jobs_status_bar = QLabel()
        layout.addWidget(self._jobs_status_bar)

    def _build_conv_tab(self):
        layout = QVBoxLayout(self._conv_tab)

        toolbar = QHBoxLayout()
        self._conv_search = QLineEdit()
        self._conv_search.setPlaceholderText("搜索招聘者/公司...")
        self._conv_search.textChanged.connect(lambda: self._refresh_convs())
        self._conv_status = QComboBox()
        self._conv_status.addItems(["全部", "无操作", "待回复", "待跟进", "已结束"])
        self._conv_status.currentTextChanged.connect(lambda: self._refresh_convs())
        self._conv_msg_type = QComboBox()
        self._conv_msg_type.addItems(["全部", "普通", "拒信", "邀投简历", "邀面试", "系统", "未知"])
        self._conv_msg_type.currentTextChanged.connect(lambda: self._refresh_convs())
        self._conv_account = QComboBox()
        self._conv_account.addItem("全部")
        self._load_account_filter()
        self._conv_account.currentTextChanged.connect(lambda: self._refresh_convs())
        self._btn_conv_refresh = QPushButton("刷新")
        self._btn_conv_refresh.clicked.connect(self._refresh_convs)
        toolbar.addWidget(self._conv_search)
        toolbar.addWidget(self._conv_status)
        toolbar.addWidget(self._conv_msg_type)
        toolbar.addWidget(self._conv_account)
        toolbar.addWidget(self._btn_conv_refresh)
        layout.addLayout(toolbar)

        self._conv_table = QTableWidget(0, 12)
        self._conv_table.setHorizontalHeaderLabels([
            "招聘者", "公司", "职位", "最后消息", "发送方", "未读数", "内容分类",
            "平台状态", "业务状态", "账号", "回复时间", "备注",
        ])
        header = self._conv_table.horizontalHeader()
        widths = [80, 120, 100, 250, 60, 60, 80, 80, 80, 100, 140, 120]
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self._conv_table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        self._conv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._conv_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._conv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._conv_table.customContextMenuRequested.connect(self._conv_context_menu)
        self._conv_table.setSortingEnabled(True)
        self._conv_table.viewport().installEventFilter(self)
        layout.addWidget(self._conv_table)

        self._conv_status_bar = QLabel()
        layout.addWidget(self._conv_status_bar)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            table = self._jobs_table if obj is self._jobs_table.viewport() else \
                    self._conv_table if obj is self._conv_table.viewport() else None
            if table:
                bar = table.horizontalScrollBar()
                delta = getattr(event, "angleDelta", lambda: None)()
                if delta:
                    bar.setValue(bar.value() - delta.y())
                    return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def refresh_all(self):
        self._refresh_jobs()
        self._refresh_convs()

    def _refresh_jobs(self):
        keyword = self._jobs_search.text().strip()
        status = self._jobs_status.currentText()
        if status == "全部":
            status = ""
        jobs = self._storage.search_jobs(keyword=keyword, status=status)
        table = self._jobs_table
        table.setSortingEnabled(False)
        table.setRowCount(len(jobs))
        for i, j in enumerate(jobs):
            table.setItem(i, 0, QTableWidgetItem(j.title))
            table.setItem(i, 1, QTableWidgetItem(j.company))
            table.setItem(i, 2, QTableWidgetItem(j.salary_raw))
            table.setItem(i, 3, QTableWidgetItem(j.status))
            table.setItem(i, 4, QTableWidgetItem(j.account))
            table.setItem(i, 5, QTableWidgetItem(j.applied_at.replace("T", " ")[:16] if j.applied_at else ""))
            table.setItem(i, 6, QTableWidgetItem(j.note))
            table.item(i, 0).setData(Qt.ItemDataRole.UserRole, j.job_id)
        table.setSortingEnabled(True)
        total = len(self._storage.search_jobs())
        filtered = len(jobs)
        self._jobs_status_bar.setText(f"总 {total} 条 | 筛选 {filtered} 条")

    def _refresh_convs(self):
        keyword = self._conv_search.text().strip()
        status = self._conv_status.currentText()
        if status == "全部":
            status = ""
        account = self._conv_account.currentText()
        if account == "全部":
            account = ""
        convs = self._storage.search_conversations(keyword=keyword, status=status, account=account)
        msg_type_filter = self._conv_msg_type.currentText()
        if msg_type_filter != "全部":
            convs = [c for c in convs if classify_msg_type(c.last_msg, c.sender, c.platform_status).value == msg_type_filter]
        table = self._conv_table
        table.setSortingEnabled(False)
        table.setRowCount(len(convs))
        for i, c in enumerate(convs):
            table.setItem(i, 0, QTableWidgetItem(c.name))
            table.setItem(i, 1, QTableWidgetItem(c.company))
            table.setItem(i, 2, QTableWidgetItem(c.position))
            table.setItem(i, 3, QTableWidgetItem(c.last_msg))
            sender_raw = c.sender
            sender_display = {"self": "自己", "other": "对方"}.get(sender_raw, sender_raw)
            item = QTableWidgetItem(sender_display)
            item.setData(Qt.ItemDataRole.UserRole + 2, sender_raw)
            table.setItem(i, 4, item)
            if c.unread_count == -1:
                display_uc = "?"
            elif c.unread_count == 0:
                display_uc = ""
            else:
                display_uc = str(c.unread_count)
            table.setItem(i, 5, QTableWidgetItem(display_uc))
            table.setItem(i, 6, QTableWidgetItem(classify_msg_type(c.last_msg, c.sender, c.platform_status)))
            table.setItem(i, 7, QTableWidgetItem(c.platform_status))
            table.setItem(i, 8, QTableWidgetItem(c.status))
            table.setItem(i, 9, QTableWidgetItem(c.account))
            table.setItem(i, 10, QTableWidgetItem(c.last_msg_time.replace("T", " ")[:16] if c.last_msg_time else ""))
            table.setItem(i, 11, QTableWidgetItem(c.note))
            table.item(i, 0).setData(Qt.ItemDataRole.UserRole, c.conv_id)
            table.item(i, 0).setData(Qt.ItemDataRole.UserRole + 1, c.account)
        table.setSortingEnabled(True)

    def _jobs_context_menu(self, pos):
        item = self._jobs_table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        job_id_item = self._jobs_table.item(row, 0)
        job_id = job_id_item.data(Qt.ItemDataRole.UserRole) if job_id_item else ""
        href_item = self._jobs_table.item(row, 1)
        href = ""

        menu = QMenu()
        act_status = QAction("修改状态", self)
        act_status.triggered.connect(lambda: self._edit_job_status(row, job_id))
        act_note = QAction("修改备注", self)
        act_note.triggered.connect(lambda: self._edit_job_note(row, job_id))
        act_delete = QAction("删除记录", self)
        act_delete.triggered.connect(lambda: self._delete_job(row, job_id))
        menu.addAction(act_status)
        menu.addAction(act_note)
        menu.addAction(act_delete)
        menu.exec(self._jobs_table.viewport().mapToGlobal(pos))

    def _jobs_cell_double_clicked(self, row, col):
        job_id_item = self._jobs_table.item(row, 0)
        job_id = job_id_item.data(Qt.ItemDataRole.UserRole) if job_id_item else ""
        if col == 3:
            self._edit_job_status(row, job_id)
        elif col == 6:
            self._edit_job_note(row, job_id)

    def _edit_job_status(self, row, job_id):
        statuses = ["已沟通", "已打招呼", "HR已读", "HR已回复", "已邀面试", "已拒绝", "已结束"]
        current = self._jobs_table.item(row, 3).text() if self._jobs_table.item(row, 3) else ""
        new_status, ok = QInputDialog.getItem(self, "修改状态", "新状态:", statuses, current=statuses.index(current) if current in statuses else 0)
        if ok and new_status:
            self._storage.update_job_status(job_id, new_status)
            self._refresh_jobs()

    def _edit_job_note(self, row, job_id):
        current = self._jobs_table.item(row, 6).text() if self._jobs_table.item(row, 6) else ""
        new_note, ok = QInputDialog.getText(self, "修改备注", "备注:", text=current)
        if ok:
            self._storage.update_job_note(job_id, new_note)
            self._refresh_jobs()

    def _delete_job(self, row, job_id):
        reply = QMessageBox.question(self, "确认删除", f"确定删除该记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._storage.delete_job(job_id)
            self._refresh_jobs()

    def _export_jobs_csv(self):
        keyword = self._jobs_search.text().strip()
        status = self._jobs_status.currentText()
        if status == "全部":
            status = ""
        jobs = self._storage.search_jobs(keyword=keyword, status=status)
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "jobs.csv", "CSV (*.csv)")
        if not path:
            return
        fieldnames = ["title", "company", "salary_raw", "status", "account", "applied_at", "href", "note"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for j in jobs:
                writer.writerow({k: getattr(j, k, "") for k in fieldnames})

    def _conv_context_menu(self, pos):
        item = self._conv_table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        conv_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        account = item.data(Qt.ItemDataRole.UserRole + 1) if item else ""

        menu = QMenu()
        act_copy = QAction("复制行", self)
        act_copy.triggered.connect(lambda: self._copy_conv_row(row))
        menu.addAction(act_copy)
        menu.addSeparator()
        act_status = QAction("修改状态", self)
        act_status.triggered.connect(lambda: self._edit_conv_status(row, conv_id, account))
        act_note = QAction("修改备注", self)
        act_note.triggered.connect(lambda: self._edit_conv_note(row, conv_id, account))
        act_delete = QAction("删除记录", self)
        act_delete.triggered.connect(lambda: self._delete_conv(row, conv_id, account))
        menu.addAction(act_status)
        menu.addAction(act_note)
        menu.addAction(act_delete)
        menu.exec(self._conv_table.viewport().mapToGlobal(pos))

    def _copy_conv_row(self, row):
        t = self._conv_table
        cells = {i: t.item(row, i).text() if t.item(row, i) else "" for i in range(12)}
        sender_item = t.item(row, 4)
        sender_raw = sender_item.data(Qt.ItemDataRole.UserRole + 2) if sender_item else ""
        msg_type = classify_msg_type(cells[3], sender_raw, cells[7])
        lines = [
            f"{cells[0]} | {cells[1]} | {cells[2]}",
            f"回复时间：{cells[10]}",
            f"消息：{cells[3]}",
            f"发送方：{'对方' if sender_raw == 'other' else '自己'}",
            f"未读数量：{cells[5]}",
            f"内容分类：{msg_type}",
            f"平台状态：{cells[7]}",
            f"业务状态：{cells[8]}",
            f"账号：{cells[9]}",
            f"备注：{cells[11]}",
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def _conv_cell_double_clicked(self, row, col):
        conv_id_item = self._conv_table.item(row, 0)
        conv_id = conv_id_item.data(Qt.ItemDataRole.UserRole) if conv_id_item else ""
        account = conv_id_item.data(Qt.ItemDataRole.UserRole + 1) if conv_id_item else ""
        if col == 8:
            self._edit_conv_status(row, conv_id, account)
        elif col == 11:
            self._edit_conv_note(row, conv_id, account)

    def _load_account_filter(self):
        from bzauto.config import get_config
        for a in get_config().accounts:
            self._conv_account.addItem(a.id)

    def _edit_conv_note(self, row, conv_id, account):
        current = self._conv_table.item(row, 11).text() if self._conv_table.item(row, 11) else ""
        new_note, ok = QInputDialog.getText(self, "修改备注", "备注:", text=current)
        if ok:
            self._storage.update_conv_note(conv_id, account, new_note)
            self._refresh_convs()

    def _edit_conv_status(self, row, conv_id, account):
        statuses = ["无操作", "待回复", "待跟进", "已结束"]
        current = self._conv_table.item(row, 8).text() if self._conv_table.item(row, 8) else ""
        new_status, ok = QInputDialog.getItem(self, "修改状态", "新状态:", statuses, current=statuses.index(current) if current in statuses else 0)
        if ok and new_status:
            self._storage.update_conv_status(conv_id, account, new_status)
            self._refresh_convs()

    def _delete_conv(self, row, conv_id, account):
        reply = QMessageBox.question(self, "确认删除", f"确定删除该记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._storage.delete_conversation(conv_id, account)
            self._refresh_convs()
