from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel

from bzauto.config import (
    AppConfig,
    get_config,
    get_config_path,
    reload_config,
    save_config,
)
from bzauto.notify import NapCatNotifier


# ===================== CityPickerDialog =====================
# 城市数据：2026-07-17 从 Boss 官方接口 https://www.zhipin.com/wapi/zpgeek/common/data/city/site.json
# 的 zpData.siteList 提取。保证与抓取时 cityName / location[0] 完全一致。
CITY_TREE = [
    {"name": "北京", "children": []},
    {"name": "上海", "children": []},
    {"name": "天津", "children": []},
    {"name": "重庆", "children": []},
    {"name": "黑龙江", "children": ["哈尔滨", "齐齐哈尔", "牡丹江", "佳木斯", "绥化", "黑河", "伊春", "大庆", "七台河", "鸡西", "鹤岗", "双鸭山", "大兴安岭地区"]},
    {"name": "吉林", "children": ["长春", "四平", "通化", "白城", "辽源", "松原", "白山", "延边朝鲜族自治州"]},
    {"name": "辽宁", "children": ["沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "铁岭", "朝阳", "盘锦", "葫芦岛"]},
    {"name": "内蒙古", "children": ["呼和浩特", "包头", "乌海", "通辽", "赤峰", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "锡林郭勒盟", "兴安盟", "阿拉善盟"]},
    {"name": "河北", "children": ["石家庄", "保定", "张家口", "承德", "唐山", "廊坊", "沧州", "衡水", "邢台", "邯郸", "秦皇岛"]},
    {"name": "山西", "children": ["太原", "大同", "阳泉", "晋中", "长治", "晋城", "临汾", "运城", "朔州", "忻州", "吕梁"]},
    {"name": "陕西", "children": ["西安", "咸阳", "延安", "榆林", "渭南", "商洛", "安康", "汉中", "宝鸡", "铜川"]},
    {"name": "山东", "children": ["济南", "青岛", "淄博", "德州", "烟台", "潍坊", "济宁", "泰安", "临沂", "菏泽", "滨州", "东营", "威海", "枣庄", "日照", "聊城"]},
    {"name": "新疆", "children": ["乌鲁木齐", "克拉玛依", "昌吉回族自治州", "巴音郭楞蒙古自治州", "博尔塔拉蒙古自治州", "伊犁哈萨克自治州", "吐鲁番", "哈密", "阿克苏地区", "克孜勒苏柯尔克孜自治州", "喀什地区", "和田地区", "塔城地区", "阿勒泰地区", "石河子", "阿拉尔", "图木舒克", "五家渠", "铁门关", "北屯市", "可克达拉市", "昆玉市", "双河市", "新星市", "胡杨河市", "白杨市"]},
    {"name": "西藏", "children": ["拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里地区"]},
    {"name": "青海", "children": ["西宁", "海东", "海北藏族自治州", "黄南藏族自治州", "海南藏族自治州", "果洛藏族自治州", "玉树藏族自治州", "海西蒙古族藏族自治州"]},
    {"name": "甘肃", "children": ["兰州", "定西", "平凉", "庆阳", "武威", "金昌", "张掖", "酒泉", "天水", "白银", "陇南", "嘉峪关", "临夏回族自治州", "甘南藏族自治州"]},
    {"name": "宁夏", "children": ["银川", "石嘴山", "吴忠", "固原", "中卫"]},
    {"name": "河南", "children": ["郑州", "安阳", "新乡", "许昌", "平顶山", "信阳", "南阳", "开封", "洛阳", "商丘", "焦作", "鹤壁", "濮阳", "周口", "漯河", "驻马店", "三门峡", "济源"]},
    {"name": "江苏", "children": ["南京", "无锡", "镇江", "苏州", "南通", "扬州", "盐城", "徐州", "淮安", "连云港", "常州", "泰州", "宿迁"]},
    {"name": "湖北", "children": ["武汉", "襄阳", "鄂州", "孝感", "黄冈", "黄石", "咸宁", "荆州", "宜昌", "十堰", "随州", "荆门", "恩施土家族苗族自治州", "仙桃", "潜江", "天门", "神农架"]},
    {"name": "浙江", "children": ["杭州", "湖州", "嘉兴", "宁波", "绍兴", "台州", "温州", "丽水", "金华", "衢州", "舟山"]},
    {"name": "安徽", "children": ["合肥", "蚌埠", "芜湖", "淮南", "马鞍山", "安庆", "宿州", "阜阳", "亳州", "滁州", "淮北", "铜陵", "宣城", "六安", "池州", "黄山"]},
    {"name": "福建", "children": ["福州", "厦门", "宁德", "莆田", "泉州", "漳州", "龙岩", "三明", "南平"]},
    {"name": "江西", "children": ["南昌", "九江", "上饶", "抚州", "宜春", "吉安", "赣州", "景德镇", "萍乡", "新余", "鹰潭"]},
    {"name": "湖南", "children": ["长沙", "湘潭", "株洲", "衡阳", "郴州", "常德", "益阳", "娄底", "邵阳", "岳阳", "张家界", "怀化", "永州", "湘西土家族苗族自治州"]},
    {"name": "贵州", "children": ["贵阳", "遵义", "安顺", "铜仁", "毕节", "六盘水", "黔东南苗族侗族自治州", "黔南布依族苗族自治州", "黔西南布依族苗族自治州"]},
    {"name": "四川", "children": ["成都", "攀枝花", "自贡", "绵阳", "南充", "达州", "遂宁", "广安", "巴中", "泸州", "宜宾", "内江", "资阳", "乐山", "眉山", "雅安", "德阳", "广元", "阿坝藏族羌族自治州", "凉山彝族自治州", "甘孜藏族自治州"]},
    {"name": "广东", "children": ["广州", "韶关", "惠州", "梅州", "汕头", "深圳", "珠海", "佛山", "肇庆", "湛江", "江门", "河源", "清远", "云浮", "潮州", "东莞", "中山", "阳江", "揭阳", "茂名", "汕尾", "东沙群岛"]},
    {"name": "云南", "children": ["昆明", "曲靖", "保山", "玉溪", "普洱", "昭通", "临沧", "丽江", "西双版纳傣族自治州", "文山壮族苗族自治州", "红河哈尼族彝族自治州", "德宏傣族景颇族自治州", "怒江傈僳族自治州", "迪庆藏族自治州", "大理白族自治州", "楚雄彝族自治州"]},
    {"name": "广西", "children": ["南宁", "崇左", "柳州", "来宾", "桂林", "梧州", "贺州", "贵港", "玉林", "百色", "钦州", "河池", "北海", "防城港"]},
    {"name": "海南", "children": ["海口", "三亚", "三沙", "儋州", "五指山", "琼海", "文昌", "万宁", "东方", "定安", "屯昌", "澄迈", "临高", "白沙黎族自治县", "昌江黎族自治县", "乐东黎族自治县", "陵水黎族自治县", "保亭黎族苗族自治县", "琼中黎族苗族自治县"]},
    {"name": "香港", "children": []},
    {"name": "澳门", "children": []},
    {"name": "台湾", "children": []},
]


class CityPickerDialog(QDialog):
    """城市黑名单选择窗口：顶部搜索框 + 下方 checkbox treeview。"""

    def __init__(self, parent=None, initial: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择城市（黑名单）")
        self.setMinimumSize(420, 520)
        self._initial = set(c.strip() for c in (initial or []) if c.strip())

        self._setup_ui()
        self._build_tree()
        self._apply_initial_checks()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 搜索框
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索城市或省份（如 杭、广东、深圳）...")
        layout.addWidget(self._search)

        # TreeView
        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        layout.addWidget(self._tree, 1)

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        # 额外辅助按钮
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._clear_all)
        btn_expand = QPushButton("全部展开")
        btn_expand.clicked.connect(lambda: self._tree.expandAll())

        extra = QHBoxLayout()
        extra.addWidget(btn_clear)
        extra.addWidget(btn_expand)
        extra.addStretch()
        extra.addWidget(btn_box)

        layout.addLayout(extra)

    def _connect_signals(self):
        self._search.textChanged.connect(self._on_search_changed)
        # 监听 check 状态变化以维护 tristate
        if hasattr(self, "_model"):
            self._model.itemChanged.connect(self._on_item_changed)

    def _build_tree(self):
        self._model = QStandardItemModel()
        root = self._model.invisibleRootItem()

        for entry in CITY_TREE:
            parent_item = QStandardItem(entry["name"])
            parent_item.setCheckable(True)
            parent_item.setEditable(False)

            children = entry.get("children", [])
            if children:
                # 父节点支持 tristate
                parent_item.setAutoTristate(True)
                for child_name in children:
                    child = QStandardItem(child_name)
                    child.setCheckable(True)
                    child.setEditable(False)
                    parent_item.appendRow(child)
            else:
                # 直辖市/特别行政区：作为叶子
                pass

            root.appendRow(parent_item)

        self._tree.setModel(self._model)
        # 默认完全收起（用户要求）。只有在有初始选中项时，才会展开包含选中城市的省份分支。
        # 搜索时也会自动展开匹配的分支。
        self._tree.collapseAll()

        # 连接 model（如果之前没连上）
        self._model.itemChanged.connect(self._on_item_changed)

    def _apply_initial_checks(self):
        if not self._initial:
            return
        root = self._model.invisibleRootItem()
        self._model.blockSignals(True)
        try:
            for i in range(root.rowCount()):
                self._check_item_by_name(root.child(i), self._initial)
        finally:
            self._model.blockSignals(False)

        # 刷新父状态（需要 block 防止 _on_item_changed 把 Partial 推到子节点上）
        self._model.blockSignals(True)
        try:
            for i in range(root.rowCount()):
                self._update_parent_check_state(root.child(i))
        finally:
            self._model.blockSignals(False)

        # 只展开包含已勾选项的省份/分支（而不是全部展开）
        self._expand_to_checked()

    def _expand_to_checked(self):
        """仅展开那些包含已选中子项的父节点。"""
        def expand_if_has_checked(item: QStandardItem):
            if item is None:
                return False
            has_checked = False
            for r in range(item.rowCount()):
                child = item.child(r)
                if child is None:
                    continue
                child_has = expand_if_has_checked(child)
                if child.checkState() == Qt.CheckState.Checked or child_has:
                    has_checked = True
            if has_checked and item.hasChildren():
                self._tree.setExpanded(item.index(), True)
            return has_checked or (item.checkState() == Qt.CheckState.Checked)

        root = self._model.invisibleRootItem()
        for i in range(root.rowCount()):
            expand_if_has_checked(root.child(i))

    def _check_item_by_name(self, item: QStandardItem, selected: set[str]):
        if item is None:
            return
        name = item.text().strip()
        if name in selected:
            item.setCheckState(Qt.CheckState.Checked)
        # 递归子
        for r in range(item.rowCount()):
            self._check_item_by_name(item.child(r), selected)

    def _on_item_changed(self, item: QStandardItem):
        if item is None:
            return
        self._model.blockSignals(True)
        try:
            if item.hasChildren():
                # 父节点被操作 → 同步所有子节点
                # 注意：只在全选/全不选时推送状态；PartiallyChecked 不要推给子节点
                state = item.checkState()
                if state != Qt.CheckState.PartiallyChecked:
                    for r in range(item.rowCount()):
                        child = item.child(r)
                        if child is not None:
                            child.setCheckState(state)
            else:
                # 子节点变化 → 更新父 tristate
                parent = item.parent()
                if parent is not None:
                    self._update_parent_check_state(parent)
        finally:
            self._model.blockSignals(False)

    def _update_parent_check_state(self, parent: QStandardItem):
        if parent is None or not parent.hasChildren():
            return
        checked = 0
        unchecked = 0
        total = parent.rowCount()
        for r in range(total):
            ch = parent.child(r)
            if ch is None:
                continue
            st = ch.checkState()
            if st == Qt.CheckState.Checked:
                checked += 1
            elif st == Qt.CheckState.Unchecked:
                unchecked += 1
        if checked == total:
            parent.setCheckState(Qt.CheckState.Checked)
        elif unchecked == total:
            parent.setCheckState(Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(Qt.CheckState.PartiallyChecked)

    def _on_search_changed(self, text: str):
        query = text.strip().lower()
        root = self._model.invisibleRootItem()
        self._filter_tree(root, query)

    def _filter_tree(self, parent_item: QStandardItem, query: str):
        """递归过滤：匹配名称或子孙有匹配则显示并展开。"""
        view = self._tree
        for row in range(parent_item.rowCount()):
            item = parent_item.child(row)
            if item is None:
                continue
            name_lower = item.text().lower()
            has_child_match = False
            if item.hasChildren():
                has_child_match = self._any_descendant_matches(item, query)
            visible = (not query) or (query in name_lower) or has_child_match

            # 通过父索引设置隐藏
            idx = item.index()
            view.setRowHidden(idx.row(), idx.parent(), not visible)

            if visible and query and item.hasChildren():
                view.setExpanded(idx, True)

            # 递归处理子（即使隐藏也要保持状态）
            if item.hasChildren():
                self._filter_tree(item, query)

    def _any_descendant_matches(self, item: QStandardItem, query: str) -> bool:
        for r in range(item.rowCount()):
            ch = item.child(r)
            if ch is None:
                continue
            if query in ch.text().lower():
                return True
            if ch.hasChildren() and self._any_descendant_matches(ch, query):
                return True
        return False

    def _clear_all(self):
        root = self._model.invisibleRootItem()
        self._model.blockSignals(True)
        try:
            for i in range(root.rowCount()):
                item = root.child(i)
                item.setCheckState(Qt.CheckState.Unchecked)
                for r in range(item.rowCount()):
                    item.child(r).setCheckState(Qt.CheckState.Unchecked)
        finally:
            self._model.blockSignals(False)

    def get_selected_cities(self) -> list[str]:
        """只收集叶子节点（具体城市）的选中名称。"""
        result: list[str] = []
        root = self._model.invisibleRootItem()
        for i in range(root.rowCount()):
            self._collect_checked_leaves(root.child(i), result)
        # 去重 + 排序（可选）
        return sorted(set(result), key=lambda x: (len(x), x))

    def _collect_checked_leaves(self, item: QStandardItem, acc: list[str]):
        if item is None:
            return
        if item.hasChildren():
            # 父节点：只看子节点状态
            for r in range(item.rowCount()):
                self._collect_checked_leaves(item.child(r), acc)
        else:
            if item.checkState() == Qt.CheckState.Checked:
                acc.append(item.text())


class ListEditorDialog(QDialog):
    """多行文本编辑对话框：每行一个项目，用于编辑逗号分隔的列表配置字段。"""

    def __init__(self, parent=None, title: str = "", items: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 320)

        layout = QVBoxLayout(self)
        self._editor = QPlainTextEdit()
        self._editor.setPlainText("\n".join(items or []))
        self._editor.setPlaceholderText("每行一个项目")
        layout.addWidget(self._editor)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_items(self) -> list[str]:
        return [l.strip() for l in self._editor.toPlainText().split("\n") if l.strip()]


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

    # ----- 列表编辑器辅助方法 -----

    def _make_list_editor_button(self, line_edit: QLineEdit, title: str) -> QPushButton:
        btn = QPushButton("编辑")
        btn.clicked.connect(lambda: self._on_edit_list(line_edit, title))
        return btn

    def _on_edit_list(self, line_edit: QLineEdit, title: str):
        items = [s.strip() for s in line_edit.text().split(",") if s.strip()]
        dlg = ListEditorDialog(self, title=title, items=items)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            line_edit.setText(", ".join(dlg.get_items()))

    def _wrap_list_editor(self, line_edit: QLineEdit, title: str) -> QWidget:
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.addWidget(line_edit)
        hbox.addWidget(self._make_list_editor_button(line_edit, title))
        return row

    # ----- 标签页构建 -----

    def _build_scrape_tab(self):
        layout = QFormLayout(self._tab_scrape)
        self._edit_whitelist = QLineEdit()
        self._edit_blacklist = QLineEdit()

        # 城市黑名单：输入框 + 选择按钮 + 编辑按钮
        self._edit_city_blacklist = QLineEdit()
        self._btn_select_city = QPushButton("选择...")
        self._btn_select_city.setToolTip("打开城市选择器（搜索 + 复选树）")
        self._btn_select_city.clicked.connect(self._on_select_cities)
        city_row = QWidget()
        city_hbox = QHBoxLayout(city_row)
        city_hbox.setContentsMargins(0, 0, 0, 0)
        city_hbox.addWidget(self._edit_city_blacklist)
        city_hbox.addWidget(self._btn_select_city)
        city_hbox.addWidget(self._make_list_editor_button(self._edit_city_blacklist, "编辑城市黑名单"))

        self._edit_company_blacklist = QLineEdit()

        self._spin_min_salary = QSpinBox()
        self._spin_max_salary = QSpinBox()
        self._edit_greeting = QPlainTextEdit()
        self._edit_greeting.setPlaceholderText("必填。自动跳转聊天页并发送此消息")
        self._edit_greeting.setMaximumHeight(80)
        self._edit_greeting.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout.addRow("白名单（逗号分隔）", self._wrap_list_editor(self._edit_whitelist, "编辑白名单"))
        layout.addRow("黑名单（逗号分隔，采集 title + 投递 JD）", self._wrap_list_editor(self._edit_blacklist, "编辑黑名单"))
        layout.addRow("城市黑名单（完整匹配）", city_row)
        layout.addRow("公司黑名单（关键字匹配）", self._wrap_list_editor(self._edit_company_blacklist, "编辑公司黑名单"))
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
        self._check_unread_trigger = QCheckBox("未读角标上升时自动扫描")
        self._spin_unread_poll = QSpinBox()
        self._spin_unread_poll.setRange(1, 300)
        self._spin_unread_poll.setSuffix(" 秒")
        self._spin_unread_cooldown = QSpinBox()
        self._spin_unread_cooldown.setRange(1, 120)
        self._spin_unread_cooldown.setSuffix(" 分钟")
        self._edit_delete_chat_time = QLineEdit()
        self._edit_delete_chat_time.setPlaceholderText("03:00")
        layout.addRow("投递时间", self._wrap_list_editor(self._edit_dispatch_times, "编辑投递时间"))
        layout.addRow("批量大小", self._spin_batch_size)
        layout.addRow("消息扫描间隔", self._spin_scan_interval)
        layout.addRow("", self._check_unread_trigger)
        layout.addRow("未读轮询间隔", self._spin_unread_poll)
        layout.addRow("未读触发冷却", self._spin_unread_cooldown)
        layout.addRow("消息删拒时间", self._edit_delete_chat_time)

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

    def _load_config(self):
        cfg = self._cfg
        self._edit_whitelist.setText(", ".join(cfg.scrape.filter.whitelist))
        self._edit_blacklist.setText(", ".join(cfg.scrape.filter.blacklist))
        self._edit_city_blacklist.setText(", ".join(cfg.scrape.filter.city_blacklist))
        self._edit_company_blacklist.setText(", ".join(cfg.scrape.filter.company_blacklist))
        self._spin_min_salary.setValue(cfg.scrape.filter.min_salary)
        self._spin_max_salary.setValue(cfg.scrape.filter.max_salary)
        self._edit_greeting.setPlainText(cfg.scrape.greeting)
        self._edit_dispatch_times.setText(", ".join(cfg.schedule.dispatch_times))
        self._spin_batch_size.setValue(cfg.schedule.dispatch_batch_size)
        self._spin_scan_interval.setValue(cfg.schedule.scan_interval_minutes)
        self._check_unread_trigger.setChecked(cfg.schedule.unread_trigger_enabled)
        self._spin_unread_poll.setValue(cfg.schedule.unread_poll_seconds)
        self._spin_unread_cooldown.setValue(cfg.schedule.unread_scan_cooldown_minutes)
        self._edit_delete_chat_time.setText(cfg.schedule.delete_chat_time)
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
        cfg.scrape.filter.city_blacklist = [s.strip() for s in self._edit_city_blacklist.text().split(",") if s.strip()]
        cfg.scrape.filter.company_blacklist = [s.strip() for s in self._edit_company_blacklist.text().split(",") if s.strip()]
        cfg.scrape.filter.min_salary = self._spin_min_salary.value()
        cfg.scrape.filter.max_salary = self._spin_max_salary.value()
        cfg.scrape.greeting = self._edit_greeting.toPlainText()
        times = [s.strip() for s in self._edit_dispatch_times.text().split(",") if s.strip()]
        if times:
            cfg.schedule.dispatch_times = times
        cfg.schedule.dispatch_batch_size = self._spin_batch_size.value()
        cfg.schedule.scan_interval_minutes = self._spin_scan_interval.value()
        cfg.schedule.unread_trigger_enabled = self._check_unread_trigger.isChecked()
        cfg.schedule.unread_poll_seconds = self._spin_unread_poll.value()
        cfg.schedule.unread_scan_cooldown_minutes = self._spin_unread_cooldown.value()
        t = self._edit_delete_chat_time.text().strip()
        if t:
            cfg.schedule.delete_chat_time = t
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

    def _on_select_cities(self):
        """弹出城市选择器对话框。"""
        current_text = self._edit_city_blacklist.text()
        current = [s.strip() for s in current_text.split(",") if s.strip()]
        dlg = CityPickerDialog(self, initial=current)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = dlg.get_selected_cities()
            self._edit_city_blacklist.setText(", ".join(selected))
