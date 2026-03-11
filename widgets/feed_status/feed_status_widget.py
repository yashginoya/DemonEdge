from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from widgets.base_widget import BaseWidget


class FeedStatusWidget(BaseWidget):
    """Displays live feed connection status, subscription count, and tick rate.

    Connects to ``MarketFeed.signals`` in ``__init__`` — no manual subscribe/unsubscribe
    to market data needed; this widget monitors the feed infrastructure itself.

    Displayed information:
    - Connection status dot + text
    - Active subscriptions count
    - Last tick received timestamp
    - Ticks per second (updated every second)
    """

    widget_id = "feed_status"

    # Private signals for thread-crossing (MarketFeed signals emit on feed thread)
    _connected_signal = Signal()
    _disconnected_signal = Signal()
    _error_signal = Signal(str)
    _tick_signal = Signal(object)  # Tick

    def __init__(self, parent=None) -> None:
        super().__init__("Feed Status", parent)

        self._tick_count_window: int = 0   # ticks in the current 1-second window
        self._last_tick_time: datetime | None = None

        self._build_ui()
        self._connect_feed_signals()

        # TPS ticker — updates every second
        self._tps_timer = QTimer(self)
        self._tps_timer.timeout.connect(self._flush_tps)
        self._tps_timer.start(1000)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Status row
        status_row = QWidget()
        row_layout = QGridLayout(status_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setColumnStretch(1, 1)

        def make_key(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
            return lbl

        def make_val(text: str = "—") -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #e6edf3; font-size: 12px; font-family: 'Consolas', monospace;")
            return lbl

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color: #f85149; font-size: 20px; padding-right: 6px;")
        self._dot.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._status_label = make_val("Disconnected")
        self._status_label.setStyleSheet("color: #f85149; font-size: 13px; font-weight: bold;")

        self._subs_label = make_val()
        self._last_tick_label = make_val()
        self._tps_label = make_val()

        row_layout.addWidget(self._dot, 0, 0, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(self._status_label, 0, 1, 1, 2)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #30363d;")

        grid = QWidget()
        grid_layout = QGridLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setSpacing(6)

        grid_layout.addWidget(make_key("Subscriptions"), 0, 0)
        grid_layout.addWidget(self._subs_label, 0, 1)
        grid_layout.addWidget(make_key("Last tick"), 1, 0)
        grid_layout.addWidget(self._last_tick_label, 1, 1)
        grid_layout.addWidget(make_key("Ticks / sec"), 2, 0)
        grid_layout.addWidget(self._tps_label, 2, 1)

        outer.addWidget(status_row)
        outer.addWidget(sep)
        outer.addWidget(grid)
        outer.addStretch()

        self.setWidget(content)

    def _connect_feed_signals(self) -> None:
        """Wire up MarketFeed signals → private Qt signals → UI update slots."""
        from feed.market_feed import MarketFeed

        feed_signals = MarketFeed.instance().signals
        feed_signals.feed_connected.connect(self._connected_signal)
        feed_signals.feed_disconnected.connect(self._disconnected_signal)
        feed_signals.feed_error.connect(self._error_signal)
        feed_signals.tick_received.connect(self._tick_signal)

        self._connected_signal.connect(self._on_connected)
        self._disconnected_signal.connect(self._on_disconnected)
        self._error_signal.connect(self._on_error)
        self._tick_signal.connect(self._on_tick)

        # Sync initial state — the feed may have already connected before this
        # widget was instantiated (race between WebSocket handshake and layout
        # restore). Without this check the widget shows "Disconnected" even
        # while ticks are flowing because it missed the one-time feed_connected
        # emission that happened before it subscribed.
        if MarketFeed.instance().is_connected:
            self._on_connected()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        self._dot.setStyleSheet("color: #3fb950; font-size: 20px; padding-right: 6px;")
        self._status_label.setText("Connected")
        self._status_label.setStyleSheet("color: #3fb950; font-size: 13px; font-weight: bold;")
        self._update_subs()

    def _on_disconnected(self) -> None:
        self._dot.setStyleSheet("color: #f85149; font-size: 20px; padding-right: 6px;")
        self._status_label.setText("Disconnected")
        self._status_label.setStyleSheet("color: #f85149; font-size: 13px; font-weight: bold;")
        self._tps_label.setText("—")

    def _on_error(self, msg: str) -> None:
        self._dot.setStyleSheet("color: #d29922; font-size: 20px; padding-right: 6px;")
        self._status_label.setText(f"Error: {msg[:60]}")
        self._status_label.setStyleSheet("color: #d29922; font-size: 13px; font-weight: bold;")

    def _on_tick(self, tick) -> None:
        self._tick_count_window += 1
        self._last_tick_time = datetime.now()
        self._last_tick_label.setText(self._last_tick_time.strftime("%H:%M:%S.%f")[:-3])

    def _flush_tps(self) -> None:
        self._tps_label.setText(str(self._tick_count_window))
        self._tick_count_window = 0
        self._update_subs()  # once per second is enough

    def _update_subs(self) -> None:
        from feed.market_feed import MarketFeed
        self._subs_label.setText(str(MarketFeed.instance().subscriber_count()))

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        from feed.market_feed import MarketFeed
        if MarketFeed.instance().is_connected:
            self._on_connected()
        else:
            self._on_disconnected()
        self._update_subs()

    def on_hide(self) -> None:
        pass

    def save_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        pass


# --- Self-registration ---
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=FeedStatusWidget.widget_id,
        display_name="Feed Status",
        category="System",
        factory=FeedStatusWidget,
        description="WebSocket feed health and diagnostics",
    )
)
