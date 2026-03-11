from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from feed.feed_models import SubscriptionMode
from models.instrument import Instrument
from models.tick import Tick
from widgets.base_widget import BaseWidget
from widgets.chart.chart_data_manager import ChartDataManager
from widgets.chart.chart_view import ChartView
from widgets.chart.timeframe import Timeframe
from utils.logger import get_logger

logger = get_logger(__name__)

_TIMEFRAMES = [Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.D1]

_BTN_NORMAL = (
    "QPushButton { background:#21262d; color:#8b949e; border:1px solid #30363d; "
    "border-radius:3px; padding:2px 8px; font-size:11px; }"
    "QPushButton:hover { background:#30363d; color:#e6edf3; }"
)
_BTN_ACTIVE = (
    "QPushButton { background:#1f6feb; color:#ffffff; border:1px solid #1f6feb; "
    "border-radius:3px; padding:2px 8px; font-size:11px; }"
)


class ChartWidget(BaseWidget):
    """OHLC chart widget with live feed via MarketFeed.

    Toolbar: symbol selector | timeframe buttons | status label.
    Price pane: OHLC bars drawn by ``OHLCItem``.
    Volume pane: volume bars drawn by ``VolumeItem``.
    """

    widget_id = "chart"

    # Bridge: feed thread → main thread
    _tick_signal = Signal(object)  # Tick

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Chart", parent)
        self.setMinimumWidth(400)

        self._instrument: Instrument | None = None
        self._timeframe: Timeframe = Timeframe.M5

        self._data_manager = ChartDataManager()
        self._chart_view = ChartView()

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        content = QWidget()
        root_layout = QVBoxLayout(content)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Toolbar ──
        toolbar = QWidget()
        toolbar.setFixedHeight(34)
        toolbar.setStyleSheet("background:#161b22; border-bottom:1px solid #30363d;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 0, 8, 0)
        tb_layout.setSpacing(6)

        # Symbol selector button
        self._symbol_btn = QPushButton("Select Symbol")
        self._symbol_btn.setStyleSheet(
            "QPushButton { background:#21262d; color:#e6edf3; border:1px solid #30363d; "
            "border-radius:3px; padding:2px 10px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background:#30363d; }"
        )
        self._symbol_btn.clicked.connect(self._open_symbol_search)
        tb_layout.addWidget(self._symbol_btn)

        tb_layout.addSpacing(8)

        # Timeframe toggle buttons
        self._tf_btn_group = QButtonGroup(self)
        self._tf_buttons: dict[Timeframe, QPushButton] = {}
        for tf in _TIMEFRAMES:
            btn = QPushButton(tf.value.label)
            btn.setCheckable(True)
            btn.setStyleSheet(_BTN_NORMAL)
            btn.clicked.connect(lambda _checked=False, t=tf: self._on_tf_clicked(t))
            self._tf_btn_group.addButton(btn)
            self._tf_buttons[tf] = btn
            tb_layout.addWidget(btn)

        self._tf_buttons[self._timeframe].setChecked(True)
        self._tf_buttons[self._timeframe].setStyleSheet(_BTN_ACTIVE)

        tb_layout.addStretch()

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#8b949e; font-size:11px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tb_layout.addWidget(self._status_label)

        # ── Placeholder (shown when no instrument) ──
        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_label = QLabel("Click 'Select Symbol' to load a chart")
        ph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_label.setStyleSheet("color:#484f58; font-size:14px;")
        ph_layout.addWidget(ph_label)

        root_layout.addWidget(toolbar)
        root_layout.addWidget(self._placeholder, 1)
        root_layout.addWidget(self._chart_view, 1)
        self._chart_view.setVisible(False)

        self.setWidget(content)

    def _wire_signals(self) -> None:
        dm = self._data_manager
        dm.signals.historical_loaded.connect(self._on_historical_loaded)
        dm.signals.bar_updated.connect(self._chart_view.update_last_bar)
        dm.signals.bar_appended.connect(self._chart_view.append_bar)
        dm.signals.error.connect(self._on_load_error)
        self._tick_signal.connect(self._on_tick_main)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _open_symbol_search(self) -> None:
        from widgets.watchlist.search_dialog import SearchDialog
        dlg = SearchDialog(self)
        dlg.instrument_selected.connect(self._on_symbol_selected)
        dlg.exec()

    def _on_symbol_selected(self, instrument: Instrument) -> None:
        self._load_chart(instrument, self._timeframe)

    def _on_tf_clicked(self, tf: Timeframe) -> None:
        # Update button styles
        for t, btn in self._tf_buttons.items():
            btn.setStyleSheet(_BTN_ACTIVE if t == tf else _BTN_NORMAL)
        self._timeframe = tf
        if self._instrument:
            self._load_chart(self._instrument, tf)

    # ------------------------------------------------------------------
    # Chart load
    # ------------------------------------------------------------------

    def _load_chart(self, instrument: Instrument, timeframe: Timeframe) -> None:
        """Unsubscribe previous, load history, subscribe live."""
        # Unsubscribe previous feed subscriptions
        self._unsubscribe_all_feeds()

        self._instrument = instrument
        self._timeframe  = timeframe

        self._symbol_btn.setText(instrument.symbol)
        self._status_label.setText("Loading…")
        self._placeholder.setVisible(False)
        self._chart_view.setVisible(True)
        self._chart_view.set_symbol(instrument.symbol)

        # Async historical load
        self._data_manager.load_historical(instrument, timeframe)

        # Subscribe live feed (QUOTE mode so we get volume too)
        self.subscribe_feed(
            instrument.exchange,
            instrument.token,
            self._tick_callback,
            SubscriptionMode.QUOTE,
        )

    def _on_historical_loaded(self, ohlc_array, vol_array) -> None:
        self._chart_view.set_data(ohlc_array, vol_array)
        self._status_label.setText("Live" if self._is_market_hours() else "Market Closed")
        logger.info("Chart loaded: %s bars for %s %s",
                    len(ohlc_array), self._instrument.symbol if self._instrument else "?",
                    self._timeframe.value.label if self._timeframe else "?")

    def _on_load_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg[:40]}")
        logger.error("Chart load error: %s", msg)

    @staticmethod
    def _is_market_hours() -> bool:
        from datetime import datetime, time
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        market_open  = time(9, 15)
        market_close = time(15, 30)
        return (now.weekday() < 5) and (market_open <= now.time() <= market_close)

    # ------------------------------------------------------------------
    # Tick handling
    # ------------------------------------------------------------------

    def _tick_callback(self, tick: Tick) -> None:
        """Called on feed thread — cross to main thread."""
        self._tick_signal.emit(tick)

    def _on_tick_main(self, tick: Tick) -> None:
        """Main thread — dispatch to data manager."""
        self._data_manager.on_tick(tick)

    # ------------------------------------------------------------------
    # BaseWidget contract
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        if self._instrument:
            self.subscribe_feed(
                self._instrument.exchange,
                self._instrument.token,
                self._tick_callback,
                SubscriptionMode.QUOTE,
            )

    def on_hide(self) -> None:
        pass  # _unsubscribe_all_feeds() is called by BaseWidget.hideEvent

    def save_state(self) -> dict:
        return {
            "symbol":          self._instrument.symbol          if self._instrument else None,
            "token":           self._instrument.token           if self._instrument else None,
            "exchange":        self._instrument.exchange        if self._instrument else None,
            "name":            self._instrument.name            if self._instrument else None,
            "instrument_type": self._instrument.instrument_type if self._instrument else None,
            "timeframe":       self._timeframe.name,
        }

    def restore_state(self, state: dict) -> None:
        if state.get("token"):
            try:
                instrument = Instrument(
                    symbol=state["symbol"],
                    token=state["token"],
                    exchange=state["exchange"],
                    name=state.get("name", state["symbol"]),
                    instrument_type=state.get("instrument_type", ""),
                )
                tf_name = state.get("timeframe", "M5")
                timeframe = Timeframe[tf_name]
                self._load_chart(instrument, timeframe)
            except Exception as exc:
                logger.warning("ChartWidget.restore_state failed: %s", exc)


# Self-register at import time
from app.widget_registry import WidgetDefinition, WidgetRegistry  # noqa: E402

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=ChartWidget.widget_id,
        display_name="Chart",
        category="Market Data",
        factory=ChartWidget,
        description="Candlestick / OHLCV price chart",
    )
)
