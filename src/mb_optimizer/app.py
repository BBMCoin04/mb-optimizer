from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from .gui import MainWindow
from .paths import resource_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MB CF Optimizer")
    app.setOrganizationName("MB")
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(resource_path("app.png"))))
    font = QFont("Microsoft YaHei UI", 10)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()
