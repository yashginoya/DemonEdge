from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from widgets.base_widget import BaseWidget
from widgets.watchlist.watchlist_tab import WatchlistTab
from utils.logger import get_logger

logger = get_logger(__name__)

_QSS = """
/* ── Tab bar ── */
QTabWidget::pane {
    border: none;
    background: #0d1117;
}
QTabBar::tab {
    background: #161b22;
    color: #8b949e;
    padding: 4px 14px;
    height: 26px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 1px;
}
QTabBar::tab:selected {
    color: #e6edf3;
    border-bottom: 2px solid #1f6feb;
    background: #0d1117;
}
QTabBar::tab:hover:!selected {
    background: #1f2937;
    color: #e6edf3;
}

/* ── Table ── */
QTableView {
    background: #0d1117;
    alternate-background-color: #161b22;
    border: none;
    outline: none;
    color: #e6edf3;
    gridline-color: transparent;
    selection-background-color: #1f2937;
    selection-color: #e6edf3;
}
QHeaderView::section {
    background: #161b22;
    color: #8b949e;
    border: none;
    border-bottom: 1px solid #30363d;
    padding: 4px 6px;
    font-size: 11px;
}

/* ── Search / buttons ── */
QLineEdit {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 3px;
    color: #e6edf3;
    padding: 2px 6px;
}
QLineEdit:focus {
    border-color: #1f6feb;
}
QPushButton {
    background: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 3px;
    padding: 2px 10px;
}
QPushButton:hover {
    background: #30363d;
}
QPushButton:pressed {
    background: #161b22;
}
QPushButton:disabled {
    color: #484f58;
}

/* ── Context menu ── */
QMenu {
    background: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
}
QMenu::item:selected {
    background: #1f6feb;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #484f58;
}
"""


class WatchlistWidget(BaseWidget):
    """Multi-tab live watchlist.

    Each tab is an independent :class:`~widgets.watchlist.watchlist_tab.WatchlistTab`
    with its own instrument list and MarketFeed subscriptions.
    """

    widget_id = "watchlist"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Watchlist", parent)
        self.setMinimumWidth(280)

        content = QWidget()
        content.setStyleSheet(_QSS)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(False)
        self._tabs.setMovable(True)
        self._tabs.tabBarDoubleClicked.connect(self._rename_tab)
        self._tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._tab_context_menu)

        # [+] corner button
        add_tab_btn = QToolButton()
        add_tab_btn.setText(" + ")
        add_tab_btn.setToolTip("New Tab")
        add_tab_btn.clicked.connect(self._add_new_tab)
        self._tabs.setCornerWidget(add_tab_btn, Qt.Corner.TopRightCorner)

        layout.addWidget(self._tabs)
        self.setWidget(content)

        # Create default tab
        self._create_tab("Watchlist 1")

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _create_tab(self, name: str) -> WatchlistTab:
        tab = WatchlistTab(self._tabs)
        self._tabs.addTab(tab, name)
        self._tabs.setCurrentWidget(tab)
        return tab

    def _add_new_tab(self) -> None:
        n = self._tabs.count() + 1
        name, ok = QInputDialog.getText(
            self, "New Tab", "Tab name:", text=f"Watchlist {n}"
        )
        if ok and name.strip():
            self._create_tab(name.strip())

    def _rename_tab(self, index: int) -> None:
        if index < 0:
            return
        current_name = self._tabs.tabText(index)
        name, ok = QInputDialog.getText(
            self, "Rename Tab", "Tab name:", text=current_name
        )
        if ok and name.strip():
            self._tabs.setTabText(index, name.strip())

    def _tab_context_menu(self, pos) -> None:
        index = self._tabs.tabBar().tabAt(pos)
        if index < 0:
            return

        menu = QMenu(self)

        rename_action = menu.addAction("Rename")
        rename_action.triggered.connect(lambda: self._rename_tab(index))

        close_action = menu.addAction("Close Tab")
        close_action.setEnabled(self._tabs.count() > 1)
        close_action.triggered.connect(lambda: self._close_tab(index))

        menu.exec(self._tabs.tabBar().mapToGlobal(pos))

    def _close_tab(self, index: int) -> None:
        if self._tabs.count() <= 1:
            return
        tab: WatchlistTab = self._tabs.widget(index)
        tab.unsubscribe_all()
        self._tabs.removeTab(index)
        tab.deleteLater()

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        """Re-subscribe all instruments in all tabs."""
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, WatchlistTab):
                tab.subscribe_all()

    def on_hide(self) -> None:
        """Unsubscribe all instruments in all tabs."""
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, WatchlistTab):
                tab.unsubscribe_all()

    def save_state(self) -> dict:
        tabs_state = []
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if isinstance(tab, WatchlistTab):
                tabs_state.append({
                    "name": self._tabs.tabText(i),
                    "state": tab.save_state(),
                })
        return {
            "tabs": tabs_state,
            "active_tab": self._tabs.currentIndex(),
        }

    def restore_state(self, state: dict) -> None:
        # Clear existing tabs (including the default "Watchlist 1")
        while self._tabs.count() > 0:
            tab = self._tabs.widget(0)
            if isinstance(tab, WatchlistTab):
                tab.unsubscribe_all()
            self._tabs.removeTab(0)
            if tab:
                tab.deleteLater()

        tabs = state.get("tabs", [])
        if not tabs:
            self._create_tab("Watchlist 1")
            return

        for entry in tabs:
            tab = self._create_tab(entry.get("name", "Watchlist"))
            tab.restore_state(entry.get("state", {}))

        active = state.get("active_tab", 0)
        if 0 <= active < self._tabs.count():
            self._tabs.setCurrentIndex(active)


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=WatchlistWidget.widget_id,
        display_name="Watchlist",
        category="Market Data",
        factory=WatchlistWidget,
    )
)
