"""Global dark theme for the trading terminal.

Color palette:
  bg-primary   #0d1117   main window / widget backgrounds
  bg-secondary #161b22   panels, toolbars, status bar, tab bars
  bg-tertiary  #1f2937   menus, dock titles, hover states
  border       #30363d   all borders and dividers
  text-primary #e6edf3   primary text
  text-muted   #8b949e   secondary / placeholder text
  accent       #1f6feb   selected items, focus rings, active tabs
  success      #3fb950   connected / positive states
  danger       #f85149   errors / disconnected
  warning      #d29922   warnings
"""

from PySide6.QtWidgets import QApplication

_THEME = """

/* ===================== BASE ===================== */

QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-size: 13px;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
}

/* ===================== MAIN WINDOW ===================== */

QMainWindow {
    background-color: #0d1117;
}

QMainWindow::separator {
    background-color: #30363d;
    width: 2px;
    height: 2px;
}

QMainWindow::separator:hover {
    background-color: #1f6feb;
}

/* ===================== MENU BAR ===================== */

QMenuBar {
    background-color: #161b22;
    color: #e6edf3;
    border-bottom: 1px solid #30363d;
    padding: 2px 0;
}

QMenuBar::item {
    background-color: transparent;
    padding: 4px 10px;
}

QMenuBar::item:selected {
    background-color: #1f2937;
    border-radius: 4px;
}

QMenuBar::item:pressed {
    background-color: #1f6feb;
}

/* ===================== MENUS ===================== */

QMenu {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 0;
}

QMenu::item {
    padding: 6px 28px 6px 16px;
}

QMenu::item:selected {
    background-color: #1f6feb;
    border-radius: 4px;
}

QMenu::item:disabled {
    color: #484f58;
}

QMenu::separator {
    height: 1px;
    background-color: #30363d;
    margin: 4px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
}

/* ===================== TOOLBAR ===================== */

QToolBar {
    background-color: #161b22;
    border: none;
    border-bottom: 1px solid #30363d;
    padding: 2px 4px;
    spacing: 4px;
}

QToolBar::separator {
    background-color: #30363d;
    width: 1px;
    margin: 4px 6px;
}

QToolButton {
    background-color: transparent;
    color: #e6edf3;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
}

QToolButton:hover {
    background-color: #1f2937;
    border-color: #30363d;
}

QToolButton:pressed {
    background-color: #1f6feb;
}

QToolButton::menu-indicator {
    image: none;
    width: 0;
}

/* ===================== DOCK WIDGETS ===================== */

QDockWidget {
    color: #e6edf3;
    titlebar-close-icon: url(none);
    titlebar-normal-icon: url(none);
}

QDockWidget::title {
    background-color: #1f2937;
    color: #e6edf3;
    padding: 5px 8px;
    border-bottom: 1px solid #30363d;
    text-align: left;
    font-weight: 600;
    font-size: 12px;
}

QDockWidget::close-button,
QDockWidget::float-button {
    background-color: transparent;
    border: none;
    padding: 2px;
    border-radius: 3px;
}

QDockWidget::close-button:hover,
QDockWidget::float-button:hover {
    background-color: #30363d;
}

/* ===================== TAB BAR ===================== */

QTabBar {
    background-color: #161b22;
}

QTabBar::tab {
    background-color: #161b22;
    color: #8b949e;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 14px;
    min-width: 80px;
}

QTabBar::tab:selected {
    color: #e6edf3;
    border-bottom: 2px solid #1f6feb;
    background-color: #0d1117;
}

QTabBar::tab:hover:!selected {
    color: #c9d1d9;
    background-color: #1f2937;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    background-color: #0d1117;
}

QTabWidget::tab-bar {
    left: 0;
}

/* ===================== STATUS BAR ===================== */

QStatusBar {
    background-color: #161b22;
    color: #8b949e;
    border-top: 1px solid #30363d;
    font-size: 12px;
}

QStatusBar::item {
    border: none;
}

/* ===================== BUTTONS ===================== */

QPushButton {
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #1f6feb;
    border-color: #1f6feb;
}

QPushButton:pressed {
    background-color: #1158c7;
}

QPushButton:disabled {
    background-color: #161b22;
    color: #484f58;
    border-color: #21262d;
}

QPushButton:flat {
    background-color: transparent;
    border: none;
}

QPushButton:flat:hover {
    color: #58a6ff;
    background-color: transparent;
}

/* ===================== LINE EDIT ===================== */

QLineEdit {
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #1f6feb;
}

QLineEdit:focus {
    border-color: #1f6feb;
}

QLineEdit:disabled {
    background-color: #161b22;
    color: #484f58;
}

QLineEdit::placeholder {
    color: #484f58;
}

/* ===================== COMBO BOX ===================== */

QComboBox {
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 28px;
}

QComboBox:focus {
    border-color: #1f6feb;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox::down-arrow {
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
    outline: none;
}

/* ===================== LABELS ===================== */

QLabel {
    background-color: transparent;
    color: #e6edf3;
}

/* ===================== SCROLL BARS ===================== */

QScrollBar:vertical {
    background-color: #0d1117;
    width: 8px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #30363d;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #484f58;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

QScrollBar:horizontal {
    background-color: #0d1117;
    height: 8px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #30363d;
    border-radius: 4px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #484f58;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}

/* ===================== SPLITTER ===================== */

QSplitter::handle {
    background-color: #30363d;
}

QSplitter::handle:hover {
    background-color: #1f6feb;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}

/* ===================== TREE / LIST / TABLE ===================== */

QTreeView, QListView, QTableView {
    background-color: #0d1117;
    color: #e6edf3;
    border: 1px solid #30363d;
    gridline-color: #21262d;
    alternate-background-color: #0d1117;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
    outline: none;
}

QTreeView::item:hover, QListView::item:hover, QTableView::item:hover {
    background-color: #1f2937;
}

QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    border: none;
    border-right: 1px solid #30363d;
    border-bottom: 1px solid #30363d;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
}

/* ===================== MESSAGE BOX ===================== */

QMessageBox {
    background-color: #161b22;
}

QMessageBox QLabel {
    color: #e6edf3;
    font-size: 13px;
}

QMessageBox QPushButton {
    min-width: 80px;
    padding: 6px 16px;
}

/* ===================== CHECK BOX ===================== */

QCheckBox {
    color: #e6edf3;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #30363d;
    border-radius: 3px;
    background-color: #21262d;
}

QCheckBox::indicator:checked {
    background-color: #1f6feb;
    border-color: #1f6feb;
}

QCheckBox::indicator:hover {
    border-color: #8b949e;
}

/* ===================== FRAME ===================== */

QFrame[frameShape="4"],
QFrame[frameShape="5"] {
    color: #30363d;
}

/* ===================== GROUP BOX ===================== */

QGroupBox {
    border: 1px solid #30363d;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 8px;
    font-weight: 600;
    color: #8b949e;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

/* ===================== TOOLTIP ===================== */

QToolTip {
    background-color: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

"""


def apply_theme(app: QApplication) -> None:
    """Apply the global dark theme to the QApplication.

    Call before creating any windows. Widget-level stylesheets can add
    overrides on top of this base theme.
    """
    app.setStyleSheet(_THEME)
