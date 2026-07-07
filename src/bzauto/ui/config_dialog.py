from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bzauto.config import (
    AppConfig,
    get_config,
    get_config_path,
    reload_config,
    save_config,
)
from bzauto.notify import NapCatNotifier


class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置")
        self.setMinimumSize(600, 500)
        self._cfg: AppConfig = get_config()
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tab_scrape = QWidget()
        self._tabs.addTab(self._tab_scrape, "采集")
        self._build_scrape_tab()

        self._tab_schedule = QWidget()
        self._tabs.addTab(self._tab_schedule, "调度")
        self._build_schedule_tab()

        self._tab_notify = QWidget()
        self._tabs.addTab(self._tab_notify, "通知")
        self._build_notify_tab()

        self._tab_accounts = QWidget()
        self._tabs.addTab(self._tab_accounts, "账号")
        self._build_accounts_tab()

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._on_save)
        btn_open = QPushButton("在编辑器中打开")
        btn_open.clicked.connect(self._on_open)
        btn_reload = QPushButton("重载")
        btn_reload.clicked.connect(self._on_reload)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_open)
        btn_layout.addWidget(btn_reload)
        layout.addLayout(btn_layout)

    def _build_scrape_tab(self):
        layout = QFormLayout(self._tab_scrape)
        self._edit_whitelist = QLineEdit()
        self._edit_blacklist = QLineEdit()
        self._spin_min_salary = QSpinBox()
        self._spin_min_salary.setRange(0, 100)
        self._spin_max_salary = QSpinBox()
        self._spin_max_salary.setRange(0, 100)
        self._edit_greeting = QPlainTextEdit()
        self._edit_greeting.setPlaceholderText("必填。自动跳转聊天页并发送此消息")
        self._edit_greeting.setMaximumHeight(80)
        self._edit_greeting.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addRow("白名单（逗号分隔）", self._edit_whitelist)
        layout.addRow("黑名单（逗号分隔）", self._edit_blacklist)
        layout.addRow("薪资下限 (K)", self._spin_min_salary)
        layout.addRow("薪资上限 (K)", self._spin_max_salary)
        layout.addRow("打招呼语", self._edit_greeting)

    def _build_schedule_tab(self):
        layout = QFormLayout(self._tab_schedule)
        self._edit_dispatch_times = QLineEdit()
        self._edit_dispatch_times.setPlaceholderText("09:00, 14:00, 19:00")
        self._spin_batch_size = QSpinBox()
        self._spin_batch_size.setRange(1, 500)
        self._spin_scan_interval = QSpinBox()
        self._spin_scan_interval.setRange(1, 1440)
        self._spin_scan_interval.setSuffix(" 分钟")
        layout.addRow("投递时间", self._edit_dispatch_times)
        layout.addRow("批量大小", self._spin_batch_size)
        layout.addRow("扫描间隔", self._spin_scan_interval)

    def _build_notify_tab(self):
        layout = QFormLayout(self._tab_notify)
        self._check_enabled = QCheckBox("启用通知")
        self._check_merge = QCheckBox("合并消息")
        self._edit_base_url = QLineEdit()
        self._combo_msg_type = QComboBox()
        self._combo_msg_type.addItems(["group", "private"])
        self._edit_target_id = QLineEdit()
        self._edit_token = QLineEdit()
        self._edit_token.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("", self._check_enabled)
        layout.addRow("", self._check_merge)
        layout.addRow("NapCat Base URL", self._edit_base_url)
        layout.addRow("消息类型", self._combo_msg_type)
        layout.addRow("目标 ID", self._edit_target_id)
        layout.addRow("Token", self._edit_token)
        btn_test = QPushButton("测试通知")
        btn_test.clicked.connect(self._on_test_notify)
        hint = QLabel("需先保存")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        row = QHBoxLayout()
        row.addWidget(btn_test)
        row.addWidget(hint)
        row.addStretch()
        layout.addRow("", row)

    def _build_accounts_tab(self):
        layout = QVBoxLayout(self._tab_accounts)
        label = QLabel("账号管理已移至独立窗口，点击控制台「账号」按钮管理。")
        label.setStyleSheet("color: gray; font-size: 13px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def _load_config(self):
        cfg = self._cfg
        self._edit_whitelist.setText(", ".join(cfg.scrape.filter.whitelist))
        self._edit_blacklist.setText(", ".join(cfg.scrape.filter.blacklist))
        self._spin_min_salary.setValue(cfg.scrape.filter.min_salary)
        self._spin_max_salary.setValue(cfg.scrape.filter.max_salary)
        self._edit_greeting.setPlainText(cfg.scrape.greeting)
        self._edit_dispatch_times.setText(", ".join(cfg.schedule.dispatch_times))
        self._spin_batch_size.setValue(cfg.schedule.dispatch_batch_size)
        self._spin_scan_interval.setValue(cfg.schedule.scan_interval_minutes)
        self._check_enabled.setChecked(cfg.notification.enabled)
        self._check_merge.setChecked(cfg.notification.merge)
        self._edit_base_url.setText(cfg.notification.napcat.base_url)
        idx = self._combo_msg_type.findText(cfg.notification.napcat.msg_type)
        if idx >= 0:
            self._combo_msg_type.setCurrentIndex(idx)
        self._edit_target_id.setText(str(cfg.notification.napcat.target_id))
        self._edit_token.setText(cfg.notification.napcat.token)

    def _collect_config(self) -> AppConfig:
        cfg = self._cfg
        cfg.scrape.filter.whitelist = [s.strip() for s in self._edit_whitelist.text().split(",") if s.strip()]
        cfg.scrape.filter.blacklist = [s.strip() for s in self._edit_blacklist.text().split(",") if s.strip()]
        cfg.scrape.filter.min_salary = self._spin_min_salary.value()
        cfg.scrape.filter.max_salary = self._spin_max_salary.value()
        cfg.scrape.greeting = self._edit_greeting.toPlainText()
        times = [s.strip() for s in self._edit_dispatch_times.text().split(",") if s.strip()]
        if times:
            cfg.schedule.dispatch_times = times
        cfg.schedule.dispatch_batch_size = self._spin_batch_size.value()
        cfg.schedule.scan_interval_minutes = self._spin_scan_interval.value()
        cfg.notification.enabled = self._check_enabled.isChecked()
        cfg.notification.merge = self._check_merge.isChecked()
        cfg.notification.napcat.base_url = self._edit_base_url.text()
        cfg.notification.napcat.msg_type = self._combo_msg_type.currentText()
        try:
            cfg.notification.napcat.target_id = int(self._edit_target_id.text())
        except ValueError:
            pass
        cfg.notification.napcat.token = self._edit_token.text()
        return cfg

    def _on_save(self):
        greeting = self._edit_greeting.toPlainText().strip()
        if not greeting:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "必填项", "打招呼语不能为空，请填写后再保存")
            return
        cfg = self._collect_config()
        save_config(cfg)
        reload_config()
        self._cfg = get_config()
        self._load_config()

    def _on_test_notify(self):
        import asyncio
        from PySide6.QtWidgets import QMessageBox

        cfg = self._collect_config()
        nc = cfg.notification.napcat
        notifier = NapCatNotifier(nc.base_url, nc.msg_type, nc.target_id, nc.token)

        async def _send():
            try:
                await notifier.send("测试通知", "这是一条来自 bosszhipin-auto 的测试消息\n如果收到说明配置正确")
                await notifier.close()
            except Exception as e:
                raise

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                async def _and_show():
                    try:
                        await _send()
                        QMessageBox.information(self, "测试通知", "发送成功")
                    except Exception as e2:
                        QMessageBox.warning(self, "发送失败", str(e2))
                loop.create_task(_and_show())
            else:
                asyncio.run(_send())
                QMessageBox.information(self, "测试通知", "发送成功")
        except Exception as e:
            QMessageBox.warning(self, "发送失败", str(e))

    def _on_open(self):
        path = get_config_path()
        if path.exists():
            os.startfile(str(path))

    def _on_reload(self):
        reload_config()
        self._cfg = get_config()
        self._load_config()
