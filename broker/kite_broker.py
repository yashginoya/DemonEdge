"""KiteBroker — Zerodha Kite Connect implementation of BaseBroker.

Wraps the official ``kiteconnect.KiteConnect`` REST client.  Do not instantiate
directly outside ``broker/`` — use ``BrokerManager.create_broker("kite", creds)``.

Authentication (OAuth redirect flow)
------------------------------------
Kite does not accept username/password directly.  The user logs in on Zerodha's
hosted page and is redirected back with a one-time ``request_token`` which is
exchanged (with the api_secret) for a daily ``access_token``.  The interactive
browser/redirect-capture lives in ``broker/kite_auth.py`` and the orchestration
in ``app/login_window.py``; this class only consumes the resulting token.

``connect()`` therefore supports two entry points:
  * a fresh ``request_token`` (set via ``set_request_token``) → exchanged for an
    access_token, which is then exposed for same-day caching, or
  * a cached ``access_token`` (passed in credentials) → validated and reused.

Param translation
-----------------
The widgets speak the app's Angel-flavoured order/margin vocabulary.  This class
translates those into Kite's vocabulary (variety in the call, MIS/CNC/NRML
products, SL/SL-M order types, ``minute``/``day`` intervals, etc.).
"""

from __future__ import annotations

from datetime import date, datetime

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException

from broker.base_broker import BaseBroker, BrokerAPIError
from models.instrument import Instrument
from models.order import Order
from models.position import Position
from utils.logger import get_logger

logger = get_logger(__name__)

_DERIVATIVE_EXCHANGES = {"NFO", "BFO", "MCX", "CDS", "BCD"}


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


# ── Vocabulary translation (app ⇄ Kite) ──────────────────────────────────────

def _product_to_kite(app_product: str, exchange: str) -> str:
    """Map app product → Kite product (MIS / CNC / NRML)."""
    p = (app_product or "").upper()
    if p in ("INTRADAY", "MIS", "BO", "CO"):
        return "MIS"
    if p in ("DELIVERY", "CNC", "CARRYFORWARD", "NRML"):
        # Cash segments hold as CNC; derivatives carry forward as NRML.
        return "NRML" if exchange.upper() in _DERIVATIVE_EXCHANGES else "CNC"
    return "MIS"


def _product_to_app(kite_product: str) -> str:
    """Map Kite product → app product label (for display in positions/orders)."""
    return {
        "MIS": "INTRADAY",
        "CNC": "DELIVERY",
        "NRML": "CARRYFORWARD",
    }.get((kite_product or "").upper(), kite_product or "")


def _ordertype_to_kite(app_type: str) -> str:
    return {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "STOPLOSS": "SL",
        "STOPLOSS_MARKET": "SL-M",
        "SL": "SL",
        "SL-M": "SL-M",
    }.get((app_type or "").upper(), "MARKET")


def _ordertype_to_app(kite_type: str) -> str:
    return {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS",
        "SL-M": "STOPLOSS_MARKET",
    }.get((kite_type or "").upper(), kite_type or "")


_INTERVAL_TO_KITE = {
    "ONE_MINUTE": "minute",
    "THREE_MINUTE": "3minute",
    "FIVE_MINUTE": "5minute",
    "TEN_MINUTE": "10minute",
    "FIFTEEN_MINUTE": "15minute",
    "THIRTY_MINUTE": "30minute",
    "ONE_HOUR": "60minute",
    "ONE_DAY": "day",
}


def _interval_to_kite(app_interval: str) -> str:
    return _INTERVAL_TO_KITE.get((app_interval or "").upper(), "minute")


class KiteBroker(BaseBroker):
    """Zerodha Kite Connect implementation of BaseBroker."""

    def __init__(self, credentials: dict) -> None:
        self._api_key: str = credentials["api_key"]
        self._api_secret: str = credentials["api_secret"]

        # Optional cached session (same-day reuse).
        self._access_token: str = credentials.get("access_token", "") or ""
        self._access_token_date: str = credentials.get("access_token_date", "") or ""

        # Set by the login flow after the browser redirect is captured.
        self._request_token: str = ""

        self._kite = KiteConnect(api_key=self._api_key)
        if self._access_token:
            self._kite.set_access_token(self._access_token)

        self._is_connected: bool = False
        self._profile: dict = {}

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def broker_key(self) -> str:
        return "kite"

    @property
    def instrument_master_url(self) -> str:
        # Informational only — fetch_instruments() uses the library, not this URL.
        return "https://api.kite.trade/instruments"

    # ------------------------------------------------------------------
    # Auth flow plumbing (used by app/login_window.py)
    # ------------------------------------------------------------------

    def login_url(self) -> str:
        """Return the Zerodha hosted login URL for this api_key."""
        return self._kite.login_url()

    def set_request_token(self, request_token: str) -> None:
        """Provide the one-time request_token captured from the redirect."""
        self._request_token = request_token

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def access_token_date(self) -> str:
        """ISO date the current access_token was issued (for same-day caching)."""
        return self._access_token_date

    @property
    def api_key(self) -> str:
        return self._api_key

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish a Kite session.

        Uses ``request_token`` (fresh login) if set, otherwise a cached
        ``access_token``.  Validates by fetching the profile.  Returns True on
        success.
        """
        if self._is_connected:
            return True
        try:
            if self._request_token:
                data = self._kite.generate_session(
                    self._request_token, api_secret=self._api_secret
                )
                self._access_token = data["access_token"]
                self._access_token_date = date.today().isoformat()
                self._kite.set_access_token(self._access_token)
                self._request_token = ""  # one-time use, consumed
            elif self._access_token:
                self._kite.set_access_token(self._access_token)
            else:
                raise BrokerAPIError(
                    "Kite login needs a request_token or a cached access_token."
                )

            # Validate the session.
            self._profile = self._kite.profile()
            self._is_connected = True
            logger.info("KiteBroker: connected as %s", self._profile.get("user_id"))
            return True
        except TokenException as exc:
            # Cached token expired / invalid — surface clearly so caller re-logs in.
            self._access_token = ""
            self._access_token_date = ""
            logger.warning("KiteBroker.connect token rejected: %s", exc)
            raise BrokerAPIError(f"Kite session expired — please log in again: {exc}") from exc
        except KiteException as exc:
            logger.exception("KiteBroker.connect() failed")
            raise BrokerAPIError(f"Kite connection failed: {exc}") from exc
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("KiteBroker.connect() raised")
            raise BrokerAPIError(f"Kite connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Drop the local session.

        Deliberately does NOT call ``invalidate_access_token`` so the cached
        token can be reused for a silent same-day reconnect (the token still
        expires on Zerodha's side at ~6 AM regardless).
        """
        self._is_connected = False
        logger.info("KiteBroker: disconnected (token retained for same-day reuse)")

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_profile(self) -> dict:
        self._require_connection()
        try:
            self._profile = self._kite.profile()
            return self._profile
        except Exception as exc:
            raise self._wrap(exc, "get_profile")

    def get_holdings(self) -> list[Position]:
        self._require_connection()
        try:
            items = self._kite.holdings() or []
            result: list[Position] = []
            for it in items:
                qty = _safe_int(it.get("quantity"))
                avg = _safe_float(it.get("average_price"))
                ltp = _safe_float(it.get("last_price"))
                realized = _safe_float(it.get("pnl"))
                unrealized = (ltp - avg) * qty if qty else 0.0
                result.append(Position(
                    symbol=it.get("tradingsymbol", ""),
                    token=str(it.get("instrument_token", "")),
                    exchange=it.get("exchange", ""),
                    product_type="DELIVERY",
                    quantity=qty,
                    average_price=avg,
                    ltp=ltp,
                    close_price=_safe_float(it.get("close_price")),
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    total_pnl=realized,
                ))
            return result
        except Exception as exc:
            raise self._wrap(exc, "get_holdings")

    def get_positions(self) -> list[Position]:
        self._require_connection()
        try:
            data = self._kite.positions() or {}
            net = data.get("net") or []
            result: list[Position] = []
            for it in net:
                qty = _safe_int(it.get("quantity"))
                avg = _safe_float(it.get("average_price"))
                ltp = _safe_float(it.get("last_price"))
                realized = _safe_float(it.get("realised"))
                unrealized = _safe_float(it.get("unrealised"))
                result.append(Position(
                    symbol=it.get("tradingsymbol", ""),
                    token=str(it.get("instrument_token", "")),
                    exchange=it.get("exchange", ""),
                    product_type=_product_to_app(it.get("product", "")),
                    quantity=qty,
                    overnight_quantity=_safe_int(it.get("overnight_quantity")),
                    buy_quantity=_safe_int(it.get("buy_quantity")),
                    sell_quantity=_safe_int(it.get("sell_quantity")),
                    average_price=avg,
                    buy_average=_safe_float(it.get("buy_price")),
                    sell_average=_safe_float(it.get("sell_price")),
                    ltp=ltp,
                    close_price=_safe_float(it.get("close_price")),
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    total_pnl=_safe_float(it.get("pnl")),
                ))
            return result
        except Exception as exc:
            raise self._wrap(exc, "get_positions")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_order_book(self) -> list[Order]:
        self._require_connection()
        try:
            items = self._kite.orders() or []
            return [
                Order(
                    order_id=str(it.get("order_id", "")),
                    symbol=it.get("tradingsymbol", ""),
                    token=str(it.get("instrument_token", "")),
                    exchange=it.get("exchange", ""),
                    side=it.get("transaction_type", ""),
                    order_type=_ordertype_to_app(it.get("order_type", "")),
                    product_type=_product_to_app(it.get("product", "")),
                    variety=it.get("variety", ""),
                    quantity=_safe_int(it.get("quantity")),
                    price=_safe_float(it.get("price")),
                    trigger_price=_safe_float(it.get("trigger_price")),
                    status=it.get("status", ""),
                    status_message=it.get("status_message") or "",
                    timestamp=_coerce_dt(it.get("order_timestamp")),
                    filled_quantity=_safe_int(it.get("filled_quantity")),
                    average_price=_safe_float(it.get("average_price")),
                )
                for it in items
            ]
        except Exception as exc:
            raise self._wrap(exc, "get_order_book")

    def place_order(self, order_params: dict) -> str:
        """Place an order. Accepts the app's Angel-style param dict."""
        self._require_connection()
        try:
            exchange = order_params.get("exchange", "")
            order_type = _ordertype_to_kite(order_params.get("ordertype", "MARKET"))
            product = _product_to_kite(order_params.get("producttype", ""), exchange)

            if (order_params.get("variety", "NORMAL") or "").upper() in ("ROBO", "BRACKET"):
                logger.warning(
                    "KiteBroker: bracket/ROBO orders are not supported on Kite — "
                    "placing a regular order instead."
                )

            price = _safe_float(order_params.get("price"))
            trigger = _safe_float(order_params.get("triggerprice"))

            kwargs = dict(
                variety=self._kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=order_params.get("tradingsymbol", ""),
                transaction_type=order_params.get("transactiontype", ""),
                quantity=_safe_int(order_params.get("quantity")),
                product=product,
                order_type=order_type,
                validity=self._kite.VALIDITY_DAY,
                tag="DemonEdge",
            )
            # Only attach price / trigger where the order type uses them.
            if order_type in ("LIMIT", "SL"):
                kwargs["price"] = price
            if order_type in ("SL", "SL-M"):
                kwargs["trigger_price"] = trigger

            order_id = self._kite.place_order(**kwargs)
            logger.info(
                "Order placed (Kite): %s %s x%s → order_id=%s",
                kwargs["transaction_type"], kwargs["tradingsymbol"],
                kwargs["quantity"], order_id,
            )
            return str(order_id)
        except Exception as exc:
            raise self._wrap(exc, "place_order")

    def cancel_order(self, order_id: str) -> bool:
        self._require_connection()
        try:
            self._kite.cancel_order(
                variety=self._kite.VARIETY_REGULAR, order_id=order_id
            )
            logger.info("Order cancelled (Kite): %s", order_id)
            return True
        except Exception as exc:
            logger.warning("KiteBroker.cancel_order failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_ltp(self, exchange: str, token: str) -> float:
        """Return last traded price.  Uses the numeric instrument_token."""
        self._require_connection()
        try:
            itoken = _safe_int(token)
            resp = self._kite.ltp(itoken)
            data = resp.get(str(itoken)) or _first_value(resp)
            return _safe_float((data or {}).get("last_price"))
        except Exception as exc:
            raise self._wrap(exc, "get_ltp")

    def get_quote(self, exchange: str, token: str) -> dict:
        """Return ``{ltp, prev_close}`` for a single instrument."""
        self._require_connection()
        try:
            itoken = _safe_int(token)
            resp = self._kite.ohlc(itoken)
            data = resp.get(str(itoken)) or _first_value(resp) or {}
            ohlc = data.get("ohlc") or {}
            return {
                "ltp": _safe_float(data.get("last_price")),
                "prev_close": _safe_float(ohlc.get("close")),
            }
        except Exception as exc:
            raise self._wrap(exc, "get_quote")

    def get_order_margin(self, margin_params: dict) -> float:
        """Return required margin in rupees for a single prospective order."""
        self._require_connection()
        try:
            exchange = margin_params.get("exchange", "")
            token = margin_params.get("token", "")
            symbol = self._resolve_symbol(exchange, token)
            if not symbol:
                raise BrokerAPIError(
                    f"get_order_margin: unknown instrument {exchange}:{token}"
                )

            price = _safe_float(margin_params.get("price"))
            order = {
                "exchange": exchange,
                "tradingsymbol": symbol,
                "transaction_type": margin_params.get("tradeType", "BUY"),
                "variety": self._kite.VARIETY_REGULAR,
                "product": _product_to_kite(margin_params.get("productType", ""), exchange),
                "order_type": "LIMIT" if price > 0 else "MARKET",
                "quantity": _safe_int(margin_params.get("qty")),
                "price": price,
                "trigger_price": 0,
            }
            resp = self._kite.order_margins([order]) or []
            if not resp:
                raise BrokerAPIError("get_order_margin: empty response")
            return _safe_float(resp[0].get("total"))
        except Exception as exc:
            raise self._wrap(exc, "get_order_margin")

    def search_instruments(self, query: str) -> list[Instrument]:
        """Search via the local instrument master (Kite has no live search API)."""
        from broker.instrument_master import InstrumentMaster
        if InstrumentMaster.is_loaded():
            return InstrumentMaster.search(query)
        return []

    def get_historical_data(
        self,
        exchange: str,
        token: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        self._require_connection()
        try:
            candles = self._kite.historical_data(
                instrument_token=_safe_int(token),
                from_date=from_date,
                to_date=to_date,
                interval=_interval_to_kite(interval),
            ) or []
            result: list[dict] = []
            for c in candles:
                ts = c.get("date")
                ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                result.append({
                    "timestamp": ts_str,
                    "open": _safe_float(c.get("open")),
                    "high": _safe_float(c.get("high")),
                    "low": _safe_float(c.get("low")),
                    "close": _safe_float(c.get("close")),
                    "volume": _safe_int(c.get("volume")),
                })
            return result
        except Exception as exc:
            raise self._wrap(exc, "get_historical_data")

    # ------------------------------------------------------------------
    # Index tokens
    #
    # Resolved live from the instrument dump (segment INDICES) by the index's
    # well-known trading symbol, so tokens are always correct.  The hardcoded
    # tokens below are only a fallback for when the master is not yet loaded.
    # ------------------------------------------------------------------

    # alias → (exchange, index trading symbol in the Kite dump)
    _INDEX_SYMBOLS: dict[str, tuple[str, str]] = {
        "NIFTY":      ("NSE", "NIFTY 50"),
        "BANKNIFTY":  ("NSE", "NIFTY BANK"),
        "FINNIFTY":   ("NSE", "NIFTY FIN SERVICE"),
        "MIDCPNIFTY": ("NSE", "NIFTY MID SELECT"),
        "SENSEX":     ("BSE", "SENSEX"),
        "BANKEX":     ("BSE", "BANKEX"),
    }

    _INDEX_FALLBACK: dict[str, dict[str, str]] = {
        "NIFTY":      {"token": "256265", "exchange": "NSE"},
        "BANKNIFTY":  {"token": "260105", "exchange": "NSE"},
        "FINNIFTY":   {"token": "257801", "exchange": "NSE"},
        "SENSEX":     {"token": "265",    "exchange": "BSE"},
    }

    def get_index_info(self, symbol: str) -> dict | None:
        entry = self._INDEX_SYMBOLS.get(symbol.upper())
        if entry is None:
            return None
        exchange, tradingsymbol = entry

        from broker.instrument_master import InstrumentMaster
        inst = InstrumentMaster.get_by_symbol(exchange, tradingsymbol)
        if inst is not None:
            return {"token": inst.token, "exchange": inst.exchange}

        # Master not loaded yet — fall back to a hardcoded token if we have one.
        return self._INDEX_FALLBACK.get(symbol.upper())

    # ------------------------------------------------------------------
    # Instrument master
    # ------------------------------------------------------------------

    def fetch_instruments(self) -> list[dict]:
        """Download Kite's full instrument dump and map to canonical records.

        Kite's native schema is already close to canonical (rupee strikes/ticks,
        CE/PE/FUT/EQ types); only ``expiry`` (a ``date`` object) needs ISO
        stringification.

        The ``/instruments`` dump is public — no access_token required — so this
        works even before a session is established.
        """
        try:
            raw = self._kite.instruments() or []
        except Exception as exc:
            raise self._wrap(exc, "fetch_instruments")

        records: list[dict] = []
        for it in raw:
            expiry = it.get("expiry")
            if isinstance(expiry, (datetime, date)):
                expiry_str = expiry.isoformat()[:10]
            else:
                expiry_str = str(expiry) if expiry else ""

            strike = _safe_float(it.get("strike"))
            records.append({
                "symbol": it.get("tradingsymbol", ""),
                "token": str(it.get("instrument_token", "")),
                "exchange": it.get("exchange", ""),
                "name": it.get("name", ""),
                "instrument_type": it.get("instrument_type", ""),
                "expiry": expiry_str,
                "strike": strike if strike > 0 else -1.0,
                "lot_size": _safe_int(it.get("lot_size", 1)) or 1,
                "tick_size": _safe_float(it.get("tick_size", 0.05)) or 0.05,
            })
        logger.info("KiteBroker: parsed %d instruments", len(records))
        return records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> None:
        if not self._is_connected:
            raise BrokerAPIError("Not connected. Call connect() first.")

    def _resolve_symbol(self, exchange: str, token: str) -> str:
        """Resolve a trading symbol from exchange+token via the instrument master."""
        from broker.instrument_master import InstrumentMaster
        inst = InstrumentMaster.get_by_token(exchange, str(token))
        return inst.symbol if inst else ""

    def _wrap(self, exc: Exception, method: str) -> BrokerAPIError:
        if isinstance(exc, BrokerAPIError):
            return exc
        logger.exception("KiteBroker.%s() failed", method)
        return BrokerAPIError(f"{method} failed: {exc}")


def _first_value(d: dict):
    for v in d.values():
        return v
    return None


def _coerce_dt(value) -> datetime:
    """Coerce a Kite order timestamp (datetime or string) to a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return datetime.now()
