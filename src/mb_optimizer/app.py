from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from .gui import MainWindow
from .paths import resource_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MB CF Optimizer")
    app.setOrganizationName("MB")
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#c5cbd0"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#18212b"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#e3e7e9"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#d4dade"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#18212b"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#dce1e4"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#18212b"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0f766e"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setWindowIcon(QIcon(str(resource_path("app.png"))))
    font = QFont("Microsoft YaHei UI", 10)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()
