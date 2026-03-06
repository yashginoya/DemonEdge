from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from models.instrument import Instrument
from models.tick import Tick
from widgets.chart.timeframe import Timeframe
from utils.logger import get_logger

logger = get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Dtype must match OHLCItem._DTYPE
_OHLC_DTYPE = np.dtype([
    ('t', np.float64),
    ('o', np.float64),
    ('h', np.float64),
    ('l', np.float64),
    ('c', np.float64),
])

_VOL_DTYPE = np.dtype([
    ('t',  np.float64),
    ('v',  np.float64),
    ('up', np.bool_),
])


class ChartDataSignals(QObject):
    """Qt signal bridge for ChartDataManager."""
    # ohlc_array (np.ndarray), volume_array (np.ndarray)
    historical_loaded = Signal(object, object)
    # t, o, h, l, c, v  — current bar changed
    bar_updated  = Signal(float, float, float, float, float, float)
    # t, o, h, l, c, v  — new bar started
    bar_appended = Signal(float, float, float, float, float, float)
    error        = Signal(str)


class _HistoricalWorker(QThread):
    """Fetches historical OHLC data off the main thread."""

    done  = Signal(object, object)   # ohlc_array, vol_array
    error = Signal(str)

    def __init__(self, instrument: Instrument, timeframe: Timeframe, parent=None) -> None:
        super().__init__(parent)
        self._instrument = instrument
        self._timeframe  = timeframe

    def run(self) -> None:
        try:
            from broker.broker_manager import BrokerManager
            broker = BrokerManager.get_broker()

            tf = self._timeframe.value
            bars_wanted = 500
            now = datetime.now(_IST)
            from_dt = datetime.fromtimestamp(
                now.timestamp() - tf.seconds * bars_wanted, tz=_IST
            )

            raw = broker.get_historical_data(
                self._instrument.exchange,
                self._instrument.token,
                tf.angel_interval,
                from_dt,
                now,
            )

            ohlc, vol = _parse_historical(raw)
            self.done.emit(ohlc, vol)

        except Exception as exc:
            logger.exception("HistoricalWorker failed")
            self.error.emit(str(exc))


def _parse_timestamp(ts_str: str) -> float:
    """Parse Angel API timestamp string to unix float.

    Angel returns timestamps as IST strings in formats like:
    '2024-01-15 10:15:00' or '2024-01-15T10:15:00+05:30'
    """
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_IST)
            return dt.timestamp()
        except ValueError:
            pass
    # Fallback: try ISO format
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except Exception:
        return 0.0


def _parse_historical(raw: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Convert broker candle list to numpy arrays."""
    if not raw:
        return np.empty(0, dtype=_OHLC_DTYPE), np.empty(0, dtype=_VOL_DTYPE)

    n = len(raw)
    ohlc = np.empty(n, dtype=_OHLC_DTYPE)
    vol  = np.empty(n, dtype=_VOL_DTYPE)

    for i, candle in enumerate(raw):
        # Broker returns: {'timestamp': str, 'open': f, 'high': f, 'low': f, 'close': f, 'volume': int}
        t = _parse_timestamp(str(candle.get('timestamp', '')))
        o = float(candle.get('open',   0))
        h = float(candle.get('high',   0))
        l = float(candle.get('low',    0))
        c = float(candle.get('close',  0))
        v = float(candle.get('volume', 0))

        ohlc[i] = (t, o, h, l, c)
        vol[i]  = (t, v, c >= o)

    return ohlc, vol


def _get_bar_start(dt: datetime, tf: Timeframe) -> float:
    """Floor *dt* to the nearest bar boundary for *tf*. Returns unix timestamp."""
    secs = tf.value.seconds
    ts = dt.timestamp()
    return math.floor(ts / secs) * secs


class ChartDataManager:
    """Manages all data logic for the chart widget.

    Not a Qt class itself — holds a ``signals`` QObject for signal emission.

    Usage::

        dm = ChartDataManager()
        dm.signals.historical_loaded.connect(chart_view.set_data)
        dm.signals.bar_updated.connect(chart_view.update_last_bar)
        dm.signals.bar_appended.connect(chart_view.append_bar)
        dm.load_historical(instrument, timeframe)
        # later, on each live tick:
        dm.on_tick(tick)
    """

    def __init__(self) -> None:
        self.signals = ChartDataSignals()
        self._instrument: Instrument | None = None
        self._timeframe: Timeframe | None   = None
        self._bars: list[dict]              = []
        self._current_bar_time: float       = 0.0
        self._worker: _HistoricalWorker | None = None

    # ------------------------------------------------------------------
    # Historical load
    # ------------------------------------------------------------------

    def load_historical(self, instrument: Instrument, timeframe: Timeframe) -> None:
        """Start async fetch. Emits ``historical_loaded`` on completion."""
        self._instrument = instrument
        self._timeframe  = timeframe
        self._bars.clear()
        self._current_bar_time = 0.0

        # Stop any previous worker
        if self._worker and self._worker.isRunning():
            self._worker.done.disconnect()
            self._worker.error.disconnect()
            self._worker.quit()

        self._worker = _HistoricalWorker(instrument, timeframe)
        self._worker.done.connect(self._on_historical_done)
        self._worker.error.connect(self._on_historical_error)
        self._worker.start()

    def _on_historical_done(self, ohlc: np.ndarray, vol: np.ndarray) -> None:
        # Rebuild internal bar list from numpy data
        self._bars.clear()
        for i in range(len(ohlc)):
            self._bars.append({
                't': float(ohlc[i]['t']),
                'o': float(ohlc[i]['o']),
                'h': float(ohlc[i]['h']),
                'l': float(ohlc[i]['l']),
                'c': float(ohlc[i]['c']),
                'v': float(vol[i]['v']) if i < len(vol) else 0.0,
            })
        if self._bars:
            self._current_bar_time = self._bars[-1]['t']

        self.signals.historical_loaded.emit(ohlc, vol)

    def _on_historical_error(self, msg: str) -> None:
        logger.error("Historical data load failed: %s", msg)
        self.signals.error.emit(msg)

    # ------------------------------------------------------------------
    # Live tick
    # ------------------------------------------------------------------

    def on_tick(self, tick: Tick) -> None:
        """Incorporate a live tick into the current or a new bar.

        Must be called from the Qt main thread (connect via signal bridge).
        """
        if self._timeframe is None or not self._bars:
            return

        tick_dt = tick.exchange_timestamp
        bar_start = _get_bar_start(tick_dt, self._timeframe)
        ltp = tick.ltp

        if bar_start == self._current_bar_time:
            bar = self._bars[-1]
            bar['h'] = max(bar['h'], ltp)
            bar['l'] = min(bar['l'], ltp)
            bar['c'] = ltp
            if tick.volume:
                bar['v'] += tick.volume
            self.signals.bar_updated.emit(
                bar['t'], bar['o'], bar['h'], bar['l'], bar['c'], bar['v']
            )
        else:
            self._current_bar_time = bar_start
            new_bar = {'t': bar_start, 'o': ltp, 'h': ltp, 'l': ltp, 'c': ltp, 'v': 0.0}
            self._bars.append(new_bar)
            self.signals.bar_appended.emit(
                new_bar['t'], new_bar['o'], new_bar['h'],
                new_bar['l'], new_bar['c'], new_bar['v']
            )
