"""账号管理窗口 — 多账号 CRUD + 登录辅助。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bzauto.browser import get_browser_manager
from bzauto.config import AccountConfig, get_config, reload_config, save_config
from bzauto.storage import Storage


class LoginPill(QWidget):
    done = Signal(str)

    def __init__(self, account_id: str, name: str, parent=None):
        super().__init__(parent)
        self._account_id = account_id
        self.setWindowTitle("登录辅助")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFixedSize(280, 60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self._label = QLabel(f"正在登录: {name}")
        self._btn_done = QPushButton("完成")
        self._btn_done.clicked.connect(self._on_done)
        layout.addWidget(self._label)
        layout.addWidget(self._btn_done)

    def _on_done(self) -> None:
        self.done.emit(self._account_id)


class AccountWindow(QWidget):
    def __init__(self, storage: Storage | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("账号管理")
        self.setMinimumSize(700, 400)
        self._storage = storage or Storage()
        self._pill: LoginPill | None = None
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._btn_add = QPushButton("新增账号")
        self._btn_add.clicked.connect(self._add)
        self._btn_login = QPushButton("登录选中")
        self._btn_login.clicked.connect(self._login_selected)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self.refresh)
        self._status_label = QLabel()
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_login)
        toolbar.addWidget(self._btn_refresh)
        toolbar.addStretch()
        toolbar.addWidget(self._status_label)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            "ID", "名称", "角色", "每日上限", "今日进度", "启用",
        ])
        header = self._table.horizontalHeader()
        widths = [120, 140, 100, 80, 80, 60]
        for i, w in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self._table.setColumnWidth(i, w)
        header.setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def refresh(self):
        cfg = get_config()
        table = self._table
        table.setRowCount(len(cfg.accounts))
        for i, acc in enumerate(cfg.accounts):
            table.setItem(i, 0, QTableWidgetItem(acc.id))
            table.setItem(i, 1, QTableWidgetItem(acc.name))
            table.setItem(i, 2, QTableWidgetItem(acc.role))

            limit_item = QTableWidgetItem(str(acc.daily_limit))
            table.setItem(i, 3, limit_item)

            remaining = self._storage.get_remaining_quota(acc.id)
            daily_count = acc.daily_limit - remaining if remaining is not None else 0
            table.setItem(i, 4, QTableWidgetItem(str(daily_count)))

            enabled_item = QTableWidgetItem("是" if acc.enabled else "否")
            enabled_item.setForeground(
                Qt.GlobalColor.darkGreen if acc.enabled else Qt.GlobalColor.gray
            )
            table.setItem(i, 5, enabled_item)

        self._status_label.setText(f"共 {len(cfg.accounts)} 个账号")

    def _get_selected_row(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[0].row()

    def _get_account_at(self, row: int) -> AccountConfig | None:
        cfg = get_config()
        if 0 <= row < len(cfg.accounts):
            return cfg.accounts[row]
        return None

    def _add(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("新增账号")
        form = QFormLayout(dlg)
        edit_id = QLineEdit()
        edit_name = QLineEdit()
        edit_role = QLineEdit("dispatcher")
        edit_limit = QLineEdit("150")
        form.addRow("ID", edit_id)
        form.addRow("名称", edit_name)
        form.addRow("角色 (scraper/dispatcher)", edit_role)
        form.addRow("每日上限", edit_limit)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        raw_id = edit_id.text().strip()
        raw_name = edit_name.text().strip()
        raw_role = edit_role.text().strip()
        raw_limit = edit_limit.text().strip()
        if not raw_id:
            return

        cfg = get_config()
        cfg.accounts.append(AccountConfig(
            id=raw_id,
            name=raw_name or raw_id,
            role=raw_role or "dispatcher",
            daily_limit=int(raw_limit) if raw_limit.isdigit() else 150,
            enabled=True,
        ))
        save_config(cfg)
        reload_config()

        bm = get_browser_manager()
        if bm:
            bm.add_account({"id": raw_id, "name": raw_name or raw_id})
        self.refresh()

    def _edit(self, row: int):
        acc = self._get_account_at(row)
        if acc is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑账号: {acc.id}")
        form = QFormLayout(dlg)

        edit_name = QLineEdit(acc.name)
        edit_role = QLineEdit(acc.role)
        edit_limit = QLineEdit(str(acc.daily_limit))
        edit_enabled = QLineEdit("是" if acc.enabled else "否")
        edit_enabled.setPlaceholderText("是 或 否")

        form.addRow("名称", edit_name)
        form.addRow("角色", edit_role)
        form.addRow("每日上限", edit_limit)
        form.addRow("启用", edit_enabled)

        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("确定")
        btn_cancel = QPushButton("取消")
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        form.addRow(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        cfg = get_config()
        idx = next((i for i, a in enumerate(cfg.accounts) if a.id == acc.id), None)
        if idx is None:
            return

        cfg.accounts[idx].name = edit_name.text().strip() or acc.id
        cfg.accounts[idx].role = edit_role.text().strip() or "dispatcher"
        try:
            cfg.accounts[idx].daily_limit = int(edit_limit.text().strip())
        except ValueError:
            pass
        enabled_text = edit_enabled.text().strip()
        if enabled_text in ("是", "yes", "true"):
            cfg.accounts[idx].enabled = True
        elif enabled_text in ("否", "no", "false"):
            cfg.accounts[idx].enabled = False

        save_config(cfg)
        reload_config()
        self._sync_manager(acc.id)
        self.refresh()

    def _delete(self, row: int):
        acc = self._get_account_at(row)
        if acc is None:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定从配置中删除账号「{acc.name}」？\n磁盘 profiles/{acc.id}/ 保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cfg = get_config()
        cfg.accounts = [a for a in cfg.accounts if a.id != acc.id]
        save_config(cfg)
        reload_config()

        bm = get_browser_manager()
        if bm:
            bm.remove_account(acc.id)
        self.refresh()

    def _toggle_enabled(self, row: int):
        acc = self._get_account_at(row)
        if acc is None:
            return
        cfg = get_config()
        idx = next((i for i, a in enumerate(cfg.accounts) if a.id == acc.id), None)
        if idx is None:
            return
        cfg.accounts[idx].enabled = not cfg.accounts[idx].enabled
        save_config(cfg)
        reload_config()
        self._sync_manager(acc.id)
        self.refresh()

    def _sync_manager(self, account_id: str):
        cfg = get_config()
        acc_cfg = next((a for a in cfg.accounts if a.id == account_id), None)
        bm = get_browser_manager()
        if bm is None:
            return
        has_tab = account_id in bm.connected_accounts()
        if acc_cfg and acc_cfg.enabled and not has_tab:
            bm.add_account({"id": acc_cfg.id, "name": acc_cfg.name})
        elif (not acc_cfg or not acc_cfg.enabled) and has_tab:
            bm.remove_account(account_id)

    def _login(self, row: int):
        acc = self._get_account_at(row)
        if acc is None:
            return
        bm = get_browser_manager()
        if bm is None:
            QMessageBox.warning(self, "错误", "浏览器未初始化")
            return

        if acc.id not in bm.connected_accounts():
            try:
                bm.add_account({"id": acc.id, "name": acc.name})
            except ValueError:
                pass

        bm.activate_account(acc.id)
        bm.load_url(acc.id, "https://www.zhipin.com")

        self._pill = LoginPill(acc.id, acc.name)
        self._pill.done.connect(self._on_login_done)
        self._pill.show()

    def _login_selected(self):
        row = self._get_selected_row()
        if row is not None:
            self._login(row)

    def _on_login_done(self, account_id: str):
        if self._pill:
            self._pill.hide()
            self._pill.deleteLater()
            self._pill = None
        bm = get_browser_manager()
        if bm:
            bm.load_url(account_id, "https://www.zhipin.com/web/geek/jobs")

    def _on_double_click(self, row: int, _col: int):
        self._login(row)

    def _context_menu(self, pos):
        item = self._table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        acc = self._get_account_at(row)
        if acc is None:
            return

        menu = QMenu()
        act_login = QAction("登录", self)
        act_login.triggered.connect(lambda: self._login(row))
        act_edit = QAction("编辑", self)
        act_edit.triggered.connect(lambda: self._edit(row))
        act_toggle = QAction(
            "禁用" if acc.enabled else "启用", self,
        )
        act_toggle.triggered.connect(lambda: self._toggle_enabled(row))
        act_delete = QAction("删除", self)
        act_delete.triggered.connect(lambda: self._delete(row))
        menu.addAction(act_login)
        menu.addAction(act_edit)
        menu.addAction(act_toggle)
        menu.addAction(act_delete)
        menu.exec(self._table.viewport().mapToGlobal(pos))
