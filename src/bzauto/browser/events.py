"""Qt 事件模拟 — send_click / send_wheel / send_key。

照搬 test.py 的手法，封装成可复用函数。所有函数必须在 qasync 主线程(QApplication)调用。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget


def send_click(view: QWidget, x: int, y: int) -> None:
    """在 view 的 (x, y) 逻辑像素坐标发送鼠标点击事件链。"""
    target = view.focusProxy() or view
    pos = QPointF(x, y)
    global_pos = view.mapToGlobal(pos.toPoint()).toPointF()

    move = QMouseEvent(
        QEvent.Type.MouseMove, pos, global_pos,
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, global_pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, pos, global_pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )

    view.setFocus()
    QApplication.sendEvent(target, move)
    QApplication.sendEvent(target, press)
    QApplication.sendEvent(target, release)


def send_wheel(
    view: QWidget,
    dy: int,
    *,
    at_x: int | None = None,
    at_y: int | None = None,
    presses: int = 1,
) -> None:
    """在 view 上发送滚轮事件。"""
    target = view.focusProxy() or view
    pos = QPointF(at_x or 0, at_y or 0)
    global_pos = view.mapToGlobal(pos.toPoint()).toPointF()

    for _ in range(presses):
        wheel = QWheelEvent(
            pos, global_pos,
            QPoint(0, 0), QPoint(0, dy),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False,
        )
        QApplication.sendEvent(target, wheel)


def send_key(view: QWidget, key: int, presses: int = 1) -> None:
    """在 view 上发送键盘事件。key 为 Qt.Key_* 常量。"""
    target = view.focusProxy() or view
    for _ in range(presses):
        press = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, press)
        QApplication.sendEvent(target, release)
