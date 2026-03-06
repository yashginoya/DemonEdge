from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtCore import Signal as _Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from app.app_state import AppState
from app.layout_manager import LayoutManager
from app.widget_registry import WidgetRegistry
from utils.logger import get_logger
from widgets.base_widget import BaseWidget

# Import widget modules to self-register with WidgetRegistry
import widgets.watchlist.watchlist_widget  # noqa: F401
import widgets.chart.chart_widget  # noqa: F401
import widgets.order_entry.order_entry_widget  # noqa: F401
import widgets.positions.positions_widget  # noqa: F401
import widgets.feed_status.feed_status_widget  # noqa: F401

logger = get_logger(__name__)


class _InstrumentMasterWorker(QThread):
    """Downloads / loads the instrument master off the main thread."""

    finished = _Signal(int)   # record count
    error = _Signal(str)

    def __init__(self, broker, parent=None) -> None:
        super().__init__(parent)
        self._broker = broker

    def run(self) -> None:
        try:
            from broker.instrument_master import InstrumentMaster
            count = InstrumentMaster.ensure_loaded(self._broker)
            self.finished.emit(count)
        except Exception as exc:
            self.error.emit(str(exc))


_APP_VERSION = "0.1.0"
_IST = ZoneInfo("Asia/Kolkata")
_LAYOUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "layout.json"
)

_AUTOSAVE_INTERVAL_MS = 3 * 60 * 1000  # 3 minutes


class MainWindow(QMainWindow):
    """Trading terminal main window — dock shell only, no business logic.

    Starts in disconnected state (banner visible, docks disabled).
    Call show_login() to present LoginWindow. On success: on_login_success()
    hides the banner and loads / restores the widget layout.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trading Terminal")
        self.setMinimumSize(1024, 600)
        self.resize(1400, 900)
        self.setDockNestingEnabled(True)
        self.setTabPosition(
            Qt.DockWidgetArea.AllDockWidgetAreas,
            QTabWidget.TabPosition.North,
        )
        self.setAnimated(True)

        # Widget management
        self._active_widgets: dict[str, BaseWidget] = {}
        self._instance_counters: dict[str, int] = {}

        # Build UI shell
        self._setup_menu()
        self._setup_toolbar()
        self._setup_banner()
        self._setup_central_widget()
        self._setup_status_bar()

        # Clock — 1-second tick
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        # Auto-save — every 3 minutes
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._autosave_timer.start(_AUTOSAVE_INTERVAL_MS)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_menu(self) -> None:
        mb = self.menuBar()

        # ---- File ----
        file_menu = mb.addMenu("File")

        connect_action = QAction("Connect to Broker…", self)
        connect_action.triggered.connect(self.show_login)
        file_menu.addAction(connect_action)

        self._disconnect_action = QAction("Disconnect", self)
        self._disconnect_action.setEnabled(False)
        self._disconnect_action.triggered.connect(self._on_disconnect)
        file_menu.addAction(self._disconnect_action)

        file_menu.addSeparator()

        save_layout_action = QAction("Save Layout", self)
        save_layout_action.triggered.connect(self._save_layout)
        file_menu.addAction(save_layout_action)

        reset_layout_action = QAction("Reset Layout", self)
        reset_layout_action.triggered.connect(self._on_reset_layout)
        file_menu.addAction(reset_layout_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ---- View ----
        view_menu = mb.addMenu("View")

        self._add_widget_menu = QMenu("Add Widget", self)
        view_menu.addMenu(self._add_widget_menu)
        view_menu.addSeparator()

        view_save_action = QAction("Save Layout", self)
        view_save_action.triggered.connect(self._save_layout)
        view_menu.addAction(view_save_action)

        # ---- Help ----
        help_menu = mb.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

        # Build the Add Widget submenu (registry is already populated from imports)
        self._populate_add_widget_menu()

    def _populate_add_widget_menu(self) -> None:
        """Rebuild the Add Widget menu from the registry."""
        self._add_widget_menu.clear()
        by_category = WidgetRegistry.get_by_category()
        for category, defns in by_category.items():
            cat_menu = self._add_widget_menu.addMenu(category)
            for defn in defns:
                action = QAction(defn.display_name, self)
                # Default-arg capture prevents late binding over the loop
                action.triggered.connect(
                    lambda _checked=False, wid=defn.widget_id: self.spawn_widget(wid)
                )
                cat_menu.addAction(action)

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Main Toolbar", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Status dot
        self._tb_dot = QLabel("●")
        self._tb_dot.setStyleSheet("color: #f85149; font-size: 16px; padding: 0 6px;")
        tb.addWidget(self._tb_dot)

        # Broker / client labels
        self._tb_status = QLabel("Disconnected")
        self._tb_status.setStyleSheet("color: #8b949e; padding-right: 4px;")
        tb.addWidget(self._tb_status)

        self._tb_broker = QLabel("")
        self._tb_broker.setStyleSheet("color: #8b949e;")
        tb.addWidget(self._tb_broker)

        self._tb_client = QLabel("")
        self._tb_client.setStyleSheet("color: #8b949e;")
        tb.addWidget(self._tb_client)

        tb.addSeparator()

        # Feed status dot + label
        self._tb_feed_dot = QLabel("●")
        self._tb_feed_dot.setStyleSheet("color: #484f58; font-size: 14px; padding: 0 4px;")
        tb.addWidget(self._tb_feed_dot)

        self._tb_feed_status = QLabel("Feed: —")
        self._tb_feed_status.setStyleSheet("color: #484f58; padding-right: 4px; font-size: 12px;")
        tb.addWidget(self._tb_feed_status)

        tb.addSeparator()

        # Market time (IST)
        self._tb_time = QLabel("")
        self._tb_time.setStyleSheet(
            "color: #8b949e; font-family: 'Consolas', monospace; padding: 0 6px;"
        )
        tb.addWidget(self._tb_time)

        tb.addSeparator()

        # Add Widget button
        self._tb_add_btn = QToolButton()
        self._tb_add_btn.setText("＋ Add Widget")
        self._tb_add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._tb_add_btn.setMenu(self._add_widget_menu)
        self._tb_add_btn.setEnabled(False)
        tb.addWidget(self._tb_add_btn)

    def _setup_central_widget(self) -> None:
        # Zero-size dummy — dock widgets expand to fill all available space.
        central = QWidget()
        central.setMaximumSize(0, 0)
        central.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCentralWidget(central)
        self.centralWidget().hide()

    def _setup_banner(self) -> None:
        # Disconnected banner lives as a secondary toolbar so it doesn't consume
        # any space once hidden (unlike a central-widget placeholder).
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self._banner = QToolBar("Connection Banner", self)
        self._banner.setObjectName("ConnectionBanner")
        self._banner.setMovable(False)
        self._banner.setFloatable(False)
        self._banner.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self._banner.setStyleSheet(
            "QToolBar#ConnectionBanner {"
            "  background-color: #2d1a1a;"
            "  border: none;"
            "  border-bottom: 2px solid #6b2020;"
            "  spacing: 0; padding: 0 16px;"
            "}"
        )
        banner_label = QLabel(
            "⚠  Not connected to broker.  Go to  File → Connect to Broker."
        )
        banner_label.setStyleSheet(
            "color: #ff7b72; font-weight: bold; font-size: 13px;"
        )
        self._banner.addWidget(banner_label)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._banner)

    def _setup_status_bar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)

        self._sb_dot = QLabel("●")
        self._sb_dot.setStyleSheet("color: #f85149; font-size: 13px; padding: 0 4px;")

        self._sb_conn = QLabel("Disconnected")
        self._sb_conn.setStyleSheet("color: #8b949e;")

        self._sb_broker = QLabel("")
        self._sb_broker.setStyleSheet("color: #8b949e;")

        self._sb_client = QLabel("")
        self._sb_client.setStyleSheet("color: #8b949e;")

        self._sb_save_time = QLabel("")
        self._sb_save_time.setStyleSheet("color: #484f58; padding-right: 8px; font-size: 11px;")

        self._sb_instruments = QLabel("")
        self._sb_instruments.setStyleSheet("color: #484f58; padding-right: 12px; font-size: 11px;")

        sb.addWidget(self._sb_dot)
        sb.addWidget(self._sb_conn)
        sb.addWidget(self._sb_broker)
        sb.addWidget(self._sb_client)
        sb.addPermanentWidget(self._sb_instruments)
        sb.addPermanentWidget(self._sb_save_time)

    # ------------------------------------------------------------------
    # Login / connection
    # ------------------------------------------------------------------

    def show_login(self) -> bool:
        """Show LoginWindow as a modal. Returns True if login succeeded."""
        from app.login_window import LoginWindow
        from PySide6.QtWidgets import QDialog

        dlg = LoginWindow(self)
        dlg.login_successful.connect(self.on_login_success)
        result = dlg.exec()
        return result == QDialog.DialogCode.Accepted

    def on_login_success(self, client_id: str, broker_name: str) -> None:
        """Called via signal after successful broker connection."""
        from broker.broker_manager import BrokerManager
        from feed.market_feed import MarketFeed

        AppState.set_connected(True)

        self._banner.setVisible(False)
        self._disconnect_action.setEnabled(True)
        self._tb_add_btn.setEnabled(True)

        self._set_connection_ui(connected=True, broker_name=broker_name, client_id=client_id)

        logger.info("Terminal connected: broker=%s client=%s", broker_name, client_id)

        # Wire feed signals to toolbar indicators (connect once; QObject handles duplicate guards)
        feed_signals = MarketFeed.instance().signals
        feed_signals.feed_connected.connect(self._on_feed_connected)
        feed_signals.feed_disconnected.connect(self._on_feed_disconnected)
        feed_signals.feed_error.connect(self._on_feed_error)

        # Start the WebSocket feed
        try:
            broker = BrokerManager.get_broker()
            MarketFeed.connect(broker)
        except Exception as exc:
            logger.error("Failed to start MarketFeed: %s", exc)

        # Load instrument master in background
        self._load_instrument_master()

        if LayoutManager.has_saved_layout():
            self._restore_layout()
        else:
            self._load_default_layout()

    def _on_disconnect(self) -> None:
        from broker.broker_manager import BrokerManager
        from feed.market_feed import MarketFeed

        # Stop the feed before broker disconnect
        try:
            MarketFeed.disconnect()
        except Exception as exc:
            logger.warning("Error stopping MarketFeed: %s", exc)

        try:
            BrokerManager.get_broker().disconnect()
        except RuntimeError:
            pass
        except Exception as exc:
            logger.warning("Error during broker disconnect: %s", exc)

        AppState.set_connected(False)
        self._banner.setVisible(True)
        self._disconnect_action.setEnabled(False)
        self._tb_add_btn.setEnabled(False)
        self._set_connection_ui(connected=False)
        self._set_feed_ui(connected=False)
        logger.info("Broker disconnected")

    # ------------------------------------------------------------------
    # Instrument master
    # ------------------------------------------------------------------

    def _load_instrument_master(self) -> None:
        from broker.broker_manager import BrokerManager
        self._sb_instruments.setText("Instruments: loading…")
        broker = BrokerManager.get_broker()
        self._im_worker = _InstrumentMasterWorker(broker, self)
        self._im_worker.finished.connect(self._on_im_loaded)
        self._im_worker.error.connect(self._on_im_error)
        self._im_worker.start()

    def _on_im_loaded(self, count: int) -> None:
        self._sb_instruments.setText(f"Instruments: {count:,}")
        logger.info("Instrument master loaded: %d records", count)

    def _on_im_error(self, msg: str) -> None:
        self._sb_instruments.setText("Instruments: —")
        logger.warning("Instrument master load failed: %s", msg)

    # ------------------------------------------------------------------
    # Feed status toolbar helpers
    # ------------------------------------------------------------------

    def _on_feed_connected(self) -> None:
        self._set_feed_ui(connected=True)

    def _on_feed_disconnected(self) -> None:
        self._set_feed_ui(connected=False)

    def _on_feed_error(self, msg: str) -> None:
        self._tb_feed_dot.setStyleSheet("color: #d29922; font-size: 14px; padding: 0 4px;")
        short = msg[:40] + "…" if len(msg) > 40 else msg
        self._tb_feed_status.setText(f"Feed: {short}")
        self._tb_feed_status.setStyleSheet("color: #d29922; padding-right: 4px; font-size: 12px;")

    def _set_feed_ui(self, connected: bool) -> None:
        if connected:
            self._tb_feed_dot.setStyleSheet("color: #3fb950; font-size: 14px; padding: 0 4px;")
            self._tb_feed_status.setText("Feed: Live")
            self._tb_feed_status.setStyleSheet(
                "color: #3fb950; padding-right: 4px; font-size: 12px;"
            )
        else:
            self._tb_feed_dot.setStyleSheet("color: #484f58; font-size: 14px; padding: 0 4px;")
            self._tb_feed_status.setText("Feed: —")
            self._tb_feed_status.setStyleSheet(
                "color: #484f58; padding-right: 4px; font-size: 12px;"
            )

    def _set_connection_ui(
        self,
        connected: bool,
        broker_name: str = "",
        client_id: str = "",
    ) -> None:
        if connected:
            dot_style = "color: #3fb950; font-size: {size}px; padding: 0 {pad};"
            text = "Connected"
            text_style = "color: #3fb950;"
        else:
            dot_style = "color: #f85149; font-size: {size}px; padding: 0 {pad};"
            text = "Disconnected"
            text_style = "color: #8b949e;"
            broker_name = ""
            client_id = ""

        self._tb_dot.setStyleSheet(dot_style.format(size=16, pad="6px"))
        self._tb_status.setText(text)
        self._tb_status.setStyleSheet(text_style)
        self._tb_broker.setText(f"  {broker_name}" if broker_name else "")
        self._tb_client.setText(f"  ·  {client_id}" if client_id else "")

        self._sb_dot.setStyleSheet(dot_style.format(size=13, pad="4px"))
        self._sb_conn.setText(text)
        self._sb_conn.setStyleSheet(text_style)
        self._sb_broker.setText(f"  |  {broker_name}" if broker_name else "")
        self._sb_client.setText(f"  |  {client_id}" if client_id else "")

    # ------------------------------------------------------------------
    # Widget management
    # ------------------------------------------------------------------

    def spawn_widget(
        self,
        widget_id: str,
        area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea,
    ) -> BaseWidget:
        """Create a new widget instance, add it to the dock, and register it."""
        n = self._instance_counters.get(widget_id, 0)
        instance_id = f"{widget_id}_{n}"
        self._instance_counters[widget_id] = n + 1

        widget = WidgetRegistry.create(widget_id)
        widget.instance_id = instance_id
        widget.setObjectName(instance_id)

        self.addDockWidget(area, widget)
        self._active_widgets[instance_id] = widget

        # Defer cleanup so closeEvent finishes before we deregister
        widget.closed.connect(
            lambda iid=instance_id: QTimer.singleShot(0, lambda: self.remove_widget(iid))
        )

        logger.debug("Widget spawned: %s", instance_id)
        return widget

    def remove_widget(self, instance_id: str) -> None:
        """Deregister a widget that has been closed by the user."""
        if instance_id in self._active_widgets:
            self._active_widgets.pop(instance_id)
            logger.debug("Widget deregistered: %s", instance_id)

    def get_first_widget_of_type(self, widget_id: str) -> "BaseWidget | None":
        """Return the first active widget with the given widget_id, or None."""
        for w in self._active_widgets.values():
            if w.widget_id == widget_id:
                return w
        return None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _load_default_layout(self) -> None:
        """Spawn widgets in the default arrangement.

        With no central widget the dock areas expand to fill the window:
          watchlist │ chart │ order_entry
          ──────────┴───────┴────────────
              positions / feed_status
        """
        # Left column
        watchlist = self.spawn_widget(
            "watchlist", Qt.DockWidgetArea.LeftDockWidgetArea
        )

        # Right area — chart takes center, order_entry splits to its right
        chart = self.spawn_widget(
            "chart", Qt.DockWidgetArea.RightDockWidgetArea
        )
        order_entry = self.spawn_widget(
            "order_entry", Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.splitDockWidget(chart, order_entry, Qt.Orientation.Horizontal)

        # Bottom row — positions and feed_status tabbed together
        positions = self.spawn_widget(
            "positions", Qt.DockWidgetArea.BottomDockWidgetArea
        )
        feed_status = self.spawn_widget(
            "feed_status", Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.tabifyDockWidget(positions, feed_status)

        # Size hints (Qt respects these best-effort)
        self.resizeDocks([watchlist], [280], Qt.Orientation.Horizontal)
        self.resizeDocks([order_entry], [300], Qt.Orientation.Horizontal)
        self.resizeDocks([positions], [180], Qt.Orientation.Vertical)

        logger.info("Default layout loaded")

    def _restore_layout(self) -> None:
        """Restore layout from layout.json."""
        restored = LayoutManager.restore(self)
        for w in restored:
            self._active_widgets[w.instance_id] = w
            # Update counters so future spawns don't collide with restored ids
            parts = w.instance_id.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                wid = parts[0]
                self._instance_counters[wid] = max(
                    self._instance_counters.get(wid, 0),
                    int(parts[1]) + 1,
                )
            w.closed.connect(
                lambda iid=w.instance_id: QTimer.singleShot(0, lambda: self.remove_widget(iid))
            )

    def _save_layout(self) -> None:
        if not self._active_widgets:
            logger.debug("No widgets to save")
            return
        LayoutManager.save(self, list(self._active_widgets.values()))
        self._update_save_time()

    def _auto_save(self) -> None:
        if self._active_widgets:
            LayoutManager.save(self, list(self._active_widgets.values()))
            n = len(self._active_widgets)
            logger.info("Layout auto-saved (%d widgets)", n)
            self._update_save_time()

    def _on_reset_layout(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Layout",
            "This will close all widgets and restore the default layout.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Close all active dock widgets
        for widget in list(self._active_widgets.values()):
            self.removeDockWidget(widget)
            widget.deleteLater()
        self._active_widgets.clear()
        self._instance_counters.clear()

        # Remove saved layout
        if os.path.exists(_LAYOUT_PATH):
            os.remove(_LAYOUT_PATH)

        if AppState.is_connected():
            self._load_default_layout()
        logger.info("Layout reset to default")

    def _update_save_time(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._sb_save_time.setText(f"Layout saved: {now}")

    # ------------------------------------------------------------------
    # Clock & About
    # ------------------------------------------------------------------

    def _update_clock(self) -> None:
        ist_now = datetime.now(tz=_IST)
        self._tb_time.setText(ist_now.strftime("%H:%M:%S  IST"))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Trading Terminal",
            f"<b>Trading Terminal</b> v{_APP_VERSION}<br><br>"
            "A Python desktop trading terminal built with PySide6.<br>"
            "Broker: Angel SmartAPI<br><br>"
            "<small>Run with: <code>uv run python main.py</code></small>",
        )

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save layout, stop feed, then exit."""
        if self._active_widgets:
            self._save_layout()

        from feed.market_feed import MarketFeed
        try:
            MarketFeed.disconnect()
        except Exception:
            pass

        event.accept()
