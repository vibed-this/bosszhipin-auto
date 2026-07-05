from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from bzauto.ui.control_panel import ControlPanel
from bzauto.ui.log_window import LogWindow


def run_ui() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    control = ControlPanel()
    log = LogWindow()

    sg = QApplication.primaryScreen().availableGeometry()
    margin = 20
    gap = 50

    log.move(sg.width() - log.width() - margin, sg.height() - log.height() - margin)
    control.move(sg.width() - control.width() - margin, log.y() - control.height() - gap)

    log.show()
    control.show()

    sys.exit(app.exec())
