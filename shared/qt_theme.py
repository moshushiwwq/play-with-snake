"""共享 Qt 主题样式（客户端与服务端共用同一套设计令牌）。"""
from __future__ import annotations

QSS = """
* {
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1a2233;
}
QMainWindow, QDialog, QWidget#Root { background: #ffffff; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #ffffff; border: none; }
QFrame#Card {
    background: #ffffff;
    border: 1px solid rgba(30, 50, 90, 0.09);
    border-radius: 14px;
}
QLabel#CardTitle { font-size: 11px; font-weight: 800; color: #8a99b8; letter-spacing: 1.4px; }
QLabel#Muted { color: #8a99b8; }
QLabel#Strong { font-weight: 800; }
QLabel#Pill {
    background: #f7fafd; border: 1px solid rgba(30, 50, 90, 0.12);
    border-radius: 12px; padding: 5px 12px; font-weight: 700; color: #3a4a66;
}
QPushButton {
    background: #ffffff; border: 1.5px solid rgba(30, 50, 90, 0.11);
    border-radius: 10px; padding: 8px 14px; font-weight: 800; color: #3a4a66;
}
QPushButton:hover { background: #f7fafd; }
QPushButton:pressed { background: #eef4fb; }
QPushButton#Primary {
    border: none; color: #04121a;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #41e39a, stop:1 #22b8f0);
}
QPushButton#Danger { color: #d64545; border: 1.5px solid rgba(214, 69, 69, 0.30); background: #fff5f5; }
QPushButton:disabled { color: #b9c3d4; background: #f7fafd; border-color: rgba(30, 50, 90, 0.06); }
QLineEdit, QSpinBox, QComboBox {
    background: #f7fafd; border: 1.5px solid rgba(30, 50, 90, 0.12);
    border-radius: 9px; padding: 7px 10px; min-height: 20px;
    selection-background-color: #22b8f0;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { background: #ffffff; border-color: #22b8f0; }
QCheckBox { spacing: 8px; color: #5a6b87; font-weight: 700; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 9px;
    border: 1.5px solid rgba(30, 50, 90, 0.18); background: #f7fafd;
}
QCheckBox::indicator:checked {
    border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #41e39a, stop:1 #22b8f0);
}
QTableWidget {
    background: #ffffff; border: 1px solid rgba(30, 50, 90, 0.09);
    border-radius: 10px; gridline-color: rgba(30, 50, 90, 0.06);
    alternate-background-color: #fbfdff;
}
QHeaderView::section {
    background: #f7fafd; border: none; border-bottom: 1px solid rgba(30, 50, 90, 0.09);
    padding: 6px; color: #8a99b8; font-weight: 800; font-size: 11px;
}
QTableWidget::item { padding: 4px 6px; }
QTableWidget::item:selected { background: rgba(34, 184, 240, 0.14); color: #1a2233; }
QPlainTextEdit, QTextEdit {
    background: #f7fafd; border: 1px solid rgba(30, 50, 90, 0.09);
    border-radius: 10px; font-family: "Consolas", "Microsoft YaHei", monospace;
    font-size: 12px; padding: 8px;
}
QTabWidget::pane { border: 1px solid rgba(30, 50, 90, 0.09); border-radius: 10px; background: #ffffff; }
QTabBar::tab {
    background: #f7fafd; border: 1px solid rgba(30, 50, 90, 0.09);
    padding: 7px 16px; margin-right: 6px; border-radius: 9px;
    color: #5a6b87; font-weight: 700;
}
QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #41e39a, stop:1 #22b8f0);
    color: #04121a; border: none;
}
QMenu {
    background: #ffffff; border: 1px solid rgba(30, 50, 90, 0.12);
    border-radius: 8px; padding: 6px;
}
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #f0f7ff; }
QMessageBox { background: #ffffff; }
QProgressBar {
    border: 1px solid rgba(30, 50, 90, 0.10); border-radius: 6px;
    background: #f7fafd; text-align: center; height: 12px;
}
QProgressBar::chunk {
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #41e39a, stop:1 #22b8f0);
}
"""
