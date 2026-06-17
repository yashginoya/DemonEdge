"""TickerWatch — per-underlying controller for the Bid/Ask Quantity Watcher.

For one underlying it tracks the *total bid* and *total ask* quantity summed
across N near-the-money option strikes on each side:

* **Call** legs  = the ATM strike's CE and the next ``N-1`` CE strikes **above**
  ATM (OTM calls).
* **Put** legs   = the ATM strike's PE and the next ``N-1`` PE strikes **below**
  ATM (OTM puts).

``total_buy_quantity`` (bid) and ``total_sell_quantity`` (ask) come live from the
feed in QUOTE mode.  As the underlying moves, the ATM strike — and therefore the
strike window — is re-centered automatically.

Threading
---------
Feed callbacks fire on the feed thread; they are bridged to the Qt main thread via
the internal ``_tick_bridge`` signal before any state is touched.  The owning
widget connects to :pyattr:`changed` to refresh the table row.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from feed.feed_manager import FeedManager
from feed.feed_models import SubscriptionMode
from models.tick import Tick
from utils.logger import get_logger
from widgets.option_chain import option_chain_builder as builder
from widgets.option_chain.option_chain_row import OptionChainRow

logger = get_logger(__name__)


class _LoadSignals(QObject):
    finished = Signal(object)   # dict payload
    failed = Signal(str)


class _LoadWorker(QRunnable):
    """Resolves chain rows, expiries, underlying token + seed LTP off the UI thread."""

    def __init__(self, underlying: str, expiry: str, exchange: str = "NFO") -> None:
        super().__init__()
        self.signals = _LoadSignals()
        self._underlying = underlying.upper().strip()
        self._expiry = expiry
        self._exchange = exchange

    def run(self) -> None:
        try:
            from broker.broker_manager import BrokerManager
            from broker.instrument_master import InstrumentMaster

            expiries = builder.get_expiries(self._underlying, self._exchange)
            if not expiries:
                self.signals.failed.emit(f"No options found for '{self._underlying}'")
                return
            expiry = self._expiry if self._expiry in expiries else expiries[0]
            rows = builder.build_chain(self._underlying, expiry, self._exchange)
            if not rows:
                self.signals.failed.emit(f"No strikes for '{self._underlying}' {expiry}")
                return

            broker = BrokerManager.get_broker()

            # Underlying token + exchange (index or stock) for the spot LTP feed.
            idx_info = broker.get_index_info(self._underlying) or {}
            if idx_info:
                u_token = idx_info["token"]
                u_exchange = idx_info["exchange"]
            else:
                results = InstrumentMaster.search(self._underlying, exchange="NSE", max_results=10)
                eq = next((r for r in results if r.instrument_type == "EQ"), results[0] if results else None)
                if eq is None:
                    self.signals.failed.emit(f"No underlying instrument for '{self._underlying}'")
                    return
                u_token = eq.token
                u_exchange = eq.exchange

            # Seed LTP so the ATM window can be picked before the first tick.
            seed_ltp = 0.0
            try:
                seed_ltp = broker.get_ltp(u_exchange, u_token)
            except Exception as exc:
                logger.debug("BidAsk: seed LTP failed for %s: %s", self._underlying, exc)

            self.signals.finished.emit({
                "rows": rows,
                "expiries": expiries,
                "expiry": expiry,
                "underlying_token": str(u_token),
                "underlying_exchange": u_exchange,
                "seed_ltp": seed_ltp,
            })
        except Exception as exc:
            logger.exception("BidAsk _LoadWorker failed")
            self.signals.failed.emit(str(exc))


class TickerWatch(QObject):
    """Live bid/ask-quantity aggregator for one underlying."""

    changed = Signal()          # row data changed → refresh the table row
    status_changed = Signal()   # status string changed
    _tick_bridge = Signal(object)  # feed thread → UI thread

    def __init__(
        self,
        underlying: str,
        expiry: str = "",
        num_strikes: int = 5,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.underlying = underlying.upper().strip()
        self.expiry = expiry
        self.num_strikes = max(1, int(num_strikes))

        # Resolved chain state
        self._rows: list[OptionChainRow] = []
        self.expiries: list[str] = []
        self._underlying_token = ""
        self._underlying_exchange = "NSE"
        self.underlying_ltp = 0.0
        self.atm_strike = 0.0
        self._atm_idx = -1

        # Live per-token bid/ask quantity
        self._buy: dict[str, float] = {}
        self._sell: dict[str, float] = {}
        self._call_tokens: list[str] = []
        self._put_tokens: list[str] = []
        self._option_subscribed: set[str] = set()
        self._underlying_subscribed = False
        self._active = False

        # Computed sums (what the model reads)
        self.call_bid = 0.0
        self.call_ask = 0.0
        self.put_bid = 0.0
        self.put_ask = 0.0

        self.status = "Loading…"
        self._tick_bridge.connect(self._on_tick_ui)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Resolve the chain and begin subscriptions (idempotent while active)."""
        if self._active:
            return
        self._active = True
        self.status = "Loading…"
        self.status_changed.emit()
        worker = _LoadWorker(self.underlying, self.expiry)
        worker.signals.finished.connect(self._on_loaded)
        worker.signals.failed.connect(self._on_load_failed)
        QThreadPool.globalInstance().start(worker)

    def stop(self) -> None:
        """Unsubscribe everything (call on widget hide / ticker removal)."""
        self._active = False
        feed = FeedManager.get_feed()
        for token in self._option_subscribed:
            feed.unsubscribe("NFO", token, self._on_feed_tick)
        self._option_subscribed.clear()
        if self._underlying_subscribed and self._underlying_token:
            feed.unsubscribe(self._underlying_exchange, self._underlying_token, self._on_feed_tick)
            self._underlying_subscribed = False

    def reload(self) -> None:
        """Full reload (after expiry change)."""
        self.stop()
        self._rows = []
        self._buy.clear()
        self._sell.clear()
        self._atm_idx = -1
        self.start()

    def set_num_strikes(self, n: int) -> None:
        self.num_strikes = max(1, int(n))
        if self._atm_idx >= 0:
            self._recenter(self._atm_idx, force=True)
            self._recompute()
            self.changed.emit()

    def set_expiry(self, expiry: str) -> None:
        if expiry and expiry != self.expiry:
            self.expiry = expiry
            self.reload()

    # ------------------------------------------------------------------
    # Load callbacks (UI thread)
    # ------------------------------------------------------------------

    def _on_loaded(self, payload: dict) -> None:
        # The ticker may have been stopped while the worker was running.
        if not self._active:
            return
        self._rows = payload["rows"]
        self.expiries = payload["expiries"]
        self.expiry = payload["expiry"]
        self._underlying_token = payload["underlying_token"]
        self._underlying_exchange = payload["underlying_exchange"]
        self.underlying_ltp = payload["seed_ltp"] or 0.0

        # Subscribe the underlying for live ATM tracking.
        if self._underlying_token and not self._underlying_subscribed:
            FeedManager.get_feed().subscribe(
                self._underlying_exchange, self._underlying_token,
                self._on_feed_tick, SubscriptionMode.LTP,
            )
            self._underlying_subscribed = True

        # Pick the initial ATM window (seed LTP, else middle of the chain).
        atm_idx = self._nearest_index(self.underlying_ltp) if self.underlying_ltp > 0 \
            else len(self._rows) // 2
        self._recenter(atm_idx, force=True)
        self._recompute()
        self.status = "Live"
        self.status_changed.emit()
        self.changed.emit()

    def _on_load_failed(self, message: str) -> None:
        self.status = message
        self.status_changed.emit()
        self.changed.emit()

    # ------------------------------------------------------------------
    # Tick handling
    # ------------------------------------------------------------------

    def _on_feed_tick(self, tick: Tick) -> None:
        """Feed thread — bridge to the UI thread."""
        self._tick_bridge.emit(tick)

    def _on_tick_ui(self, tick: Tick) -> None:
        if tick.token == self._underlying_token:
            self.underlying_ltp = tick.ltp
            new_idx = self._nearest_index(tick.ltp)
            if new_idx != self._atm_idx and new_idx >= 0:
                self._recenter(new_idx)
                self._recompute()
                self.changed.emit()
            return

        # Option tick — store latest bid/ask and recompute.
        if tick.total_buy_quantity is not None:
            self._buy[tick.token] = tick.total_buy_quantity
        if tick.total_sell_quantity is not None:
            self._sell[tick.token] = tick.total_sell_quantity
        self._recompute()
        self.changed.emit()

    # ------------------------------------------------------------------
    # Strike window management
    # ------------------------------------------------------------------

    def _nearest_index(self, ltp: float) -> int:
        if not self._rows or ltp <= 0:
            return self._atm_idx
        return min(range(len(self._rows)), key=lambda i: abs(self._rows[i].strike - ltp))

    def _recenter(self, atm_idx: int, force: bool = False) -> None:
        """Select the call/put strike windows around *atm_idx* and re-subscribe."""
        if not self._rows:
            return
        if atm_idx == self._atm_idx and not force:
            return
        self._atm_idx = atm_idx
        self.atm_strike = self._rows[atm_idx].strike
        n = self.num_strikes

        # Calls: ATM and N-1 strikes above (OTM calls).
        call_rows = self._rows[atm_idx: atm_idx + n]
        # Puts: ATM and N-1 strikes below (OTM puts).
        put_lo = max(0, atm_idx - (n - 1))
        put_rows = self._rows[put_lo: atm_idx + 1]

        self._call_tokens = [r.ce_token for r in call_rows if r.ce_token]
        self._put_tokens = [r.pe_token for r in put_rows if r.pe_token]

        desired = set(self._call_tokens) | set(self._put_tokens)
        feed = FeedManager.get_feed()

        for token in self._option_subscribed - desired:
            feed.unsubscribe("NFO", token, self._on_feed_tick)
            self._buy.pop(token, None)
            self._sell.pop(token, None)
        for token in desired - self._option_subscribed:
            feed.subscribe("NFO", token, self._on_feed_tick, SubscriptionMode.QUOTE)

        self._option_subscribed = desired

    def _recompute(self) -> None:
        self.call_bid = sum(self._buy.get(t, 0.0) for t in self._call_tokens)
        self.call_ask = sum(self._sell.get(t, 0.0) for t in self._call_tokens)
        self.put_bid = sum(self._buy.get(t, 0.0) for t in self._put_tokens)
        self.put_ask = sum(self._sell.get(t, 0.0) for t in self._put_tokens)

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def call_ratio(self) -> float:
        return self.call_bid / self.call_ask if self.call_ask else 0.0

    @property
    def put_ratio(self) -> float:
        return self.put_bid / self.put_ask if self.put_ask else 0.0

    def config_dict(self) -> dict:
        return {
            "underlying": self.underlying,
            "expiry": self.expiry,
            "num_strikes": self.num_strikes,
        }
