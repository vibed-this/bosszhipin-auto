import sys, json
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from PySide6.QtCore import QUrl, QTimer, Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QBrush
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage


class DotOverlay(QWidget):
    """Transparent overlay that draws a red dot for 2 seconds."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dot = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def show_dot(self, cx, cy):
        self._dot = (cx, cy)
        self.update()
        # QTimer.singleShot(2000, self._clear_dot)

    def _clear_dot(self):
        self._dot = None
        self.update()

    def paintEvent(self, event):
        if self._dot:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor("red")))
            painter.setPen(Qt.PenStyle.NoPen)
            cx, cy = self._dot
            painter.drawEllipse(int(cx) - 5, int(cy) - 5, 10, 10)
            painter.end()


class ClickPage(QWebEnginePage):
    def __init__(self, view, overlay):
        super().__init__(view)
        self.view = view
        self.overlay = overlay

    def on_load_finished(self, ok):
        url = self.url().toString()
        print(f"[test] loadFinished: ok={ok} url={url}", file=sys.stderr)
        if not ok:
            return
        QTimer.singleShot(3000, self.check_page)

    def check_page(self):
        self.toHtml(self._on_html_check)

    def _on_html_check(self, html):
        if "page-security" in html or "正在加载" in html:
            QTimer.singleShot(3000, self.check_page)
            return
        print("[test] real page loaded, waiting for render...", file=sys.stderr)
        QTimer.singleShot(2000, self.find_and_click_first_job)

    def find_and_click_first_job(self):
        js = r"""
        (() => {
            const el = document.querySelectorAll('.job-card-box')[1];
            if (!el) return 'null';
            el.scrollIntoView({ block: 'center' });
            const r = el.getBoundingClientRect();
            return JSON.stringify({
                x: r.x, y: r.y, w: r.width, h: r.height,
                cx: Math.round(r.x + r.width / 2),
                cy: Math.round(r.y + r.height / 2)
            });
        })()
        """
        self.runJavaScript(js, self._on_bbox)

    def _on_bbox(self, raw):
            if not raw or raw == "null":
                print("[test] no job-card-box found", file=sys.stderr)
                return
            bbox = json.loads(raw)
            cx, cy = bbox["cx"], bbox["cy"]
            print(f"[test] second job card center=({cx}, {cy}) size=({bbox['w']}x{bbox['h']})", file=sys.stderr)

            # 1. 准备局部和全局坐标
            pos = QPointF(cx, cy)
            # 将局部坐标转换为相对于屏幕的全局坐标，QMouseEvent 需要这个来确保高分屏下的准确性
            global_pos = self.view.mapToGlobal(pos.toPoint()).toPointF()

            # 2. 获取真正的渲染接收器
            target = self.view.focusProxy()
            if not target:
                target = self.view  # 兜底防御

            # 3. 构造完整的事件链：Move -> Press -> Release
            # 注意 PySide6 的 QMouseEvent 构造函数签名：(type, localPos, globalPos, button, buttons, modifiers)
            move = QMouseEvent(QEvent.Type.MouseMove, pos, global_pos, 
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            
            press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, global_pos, 
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            
            release = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, global_pos, 
                                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)

            # 4. 发送事件
            self.view.setFocus() # 确保视图处于激活状态
            
            QApplication.sendEvent(target, move)
            # 最好在 move 和 click 之间给前端框架一点点时间来触发 hover 状态的 JS 回调
            # 这里为了演示依然用延时同步发送，实际复杂场景可考虑用 QTimer 拆解
            QApplication.sendEvent(target, press)
            QApplication.sendEvent(target, release)

            self.overlay.show_dot(cx, cy)
            print(f"[test] click sent to focusProxy + red dot at ({cx},{cy})", file=sys.stderr)

def main():
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("BossZhipin")
    view = QWebEngineView()
    overlay = DotOverlay()
    page = ClickPage(view, overlay)
    view.setPage(page)
    view.loadFinished.connect(page.on_load_finished)
    view.load(QUrl("https://www.zhipin.com/web/geek/jobs"))
    win.setCentralWidget(view)
    win.resize(1024, 768)
    win.show()

    # overlay as child of the web view, covering it entirely
    overlay.setParent(view)
    overlay.setGeometry(0, 0, view.width(), view.height())
    overlay.raise_()
    overlay.show()

    def resize_overlay():
        overlay.setGeometry(0, 0, view.width(), view.height())
        overlay.raise_()
    win.resizeEvent = lambda e: (resize_overlay(), QMainWindow.resizeEvent(win, e))

    QTimer.singleShot(120000, lambda: print("[test] timeout", file=sys.stderr))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
