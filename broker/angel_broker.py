from datetime import datetime

import pyotp
from SmartApi import SmartConnect

from broker.base_broker import BaseBroker, BrokerAPIError
from models.instrument import Instrument
from models.order import Order
from models.position import Position
from utils.logger import get_logger

logger = get_logger(__name__)


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


class AngelBroker(BaseBroker):
    """Angel SmartAPI implementation of BaseBroker.

    Pass a credentials dict with keys: api_key, client_id, password, totp_secret.
    Do not instantiate directly outside broker/ — use BrokerManager.create_broker().
    """

    def __init__(self, credentials: dict) -> None:
        self._api_key: str = credentials["api_key"]
        self._client_id: str = credentials["client_id"]
        self._password: str = credentials["password"]
        self._totp_secret: str = credentials["totp_secret"]

        self._smart: SmartConnect | None = None
        self._auth_token: str = ""
        self._refresh_token: str = ""
        self._feed_token: str = ""
        self._is_connected: bool = False

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Authenticate with Angel SmartAPI. Returns True on success."""
        try:
            self._smart = SmartConnect(api_key=self._api_key)
            totp = pyotp.TOTP(self._totp_secret).now()
            resp = self._smart.generateSession(self._client_id, self._password, totp)

            if not resp or not resp.get("status"):
                msg = resp.get("message", "Unknown error") if resp else "No response from API"
                logger.error("AngelBroker.connect failed: %s", msg)
                return False

            data = resp.get("data", {})
            self._auth_token = data.get("jwtToken", "")
            self._refresh_token = data.get("refreshToken", "")
            self._feed_token = self._smart.getfeedToken()
            self._is_connected = True
            logger.info("AngelBroker: connected as %s", self._client_id)
            return True

        except Exception as exc:
            logger.exception("AngelBroker.connect() raised an exception")
            raise BrokerAPIError(f"Connection failed: {exc}") from exc

    def disconnect(self) -> None:
        """Terminate the Angel session."""
        if self._smart and self._is_connected:
            try:
                self._smart.terminateSession(self._client_id)
                logger.info("AngelBroker: session terminated")
            except Exception as exc:
                logger.warning("AngelBroker.disconnect() error (ignored): %s", exc)
            finally:
                self._is_connected = False

    def get_feed_token(self) -> str:
        """Return the feed token needed by MarketFeed."""
        return self._feed_token

    # ------------------------------------------------------------------
    # BaseBroker identity properties (used by InstrumentMaster)
    # ------------------------------------------------------------------

    @property
    def broker_key(self) -> str:
        return "angel"

    @property
    def instrument_master_url(self) -> str:
        return (
            "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
        )

    # ------------------------------------------------------------------
    # Properties for MarketFeed — read by feed/market_feed.py on connect
    # ------------------------------------------------------------------

    @property
    def auth_token(self) -> str:
        return self._auth_token

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def client_code(self) -> str:
        """Angel WebSocket calls this 'clientCode' — maps to client_id."""
        return self._client_id

    @property
    def feed_token(self) -> str:
        return self._feed_token

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_profile(self) -> dict:
        """Return the user profile dict from Angel SmartAPI."""
        self._require_connection()
        try:
            resp = self._smart.getProfile(self._refresh_token)
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_profile failed: {resp}")
            return resp.get("data", {})
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_profile() failed")
            raise BrokerAPIError(f"get_profile failed: {exc}") from exc

    def get_holdings(self) -> list[Position]:
        """Return equity holdings as Position objects."""
        self._require_connection()
        try:
            resp = self._smart.holding()
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_holdings failed: {resp}")
            items = resp.get("data") or []
            return [
                Position(
                    symbol=item.get("tradingsymbol", ""),
                    exchange=item.get("exchange", ""),
                    quantity=_safe_int(item.get("quantity")),
                    average_price=_safe_float(item.get("averageprice")),
                    ltp=_safe_float(item.get("ltp")),
                    pnl=_safe_float(item.get("profitandloss")),
                )
                for item in items
            ]
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_holdings() failed")
            raise BrokerAPIError(f"get_holdings failed: {exc}") from exc

    def get_positions(self) -> list[Position]:
        """Return intraday/overnight positions as Position objects."""
        self._require_connection()
        try:
            resp = self._smart.position()
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_positions failed: {resp}")
            items = resp.get("data") or []
            return [
                Position(
                    symbol=item.get("tradingsymbol", ""),
                    exchange=item.get("exchange", ""),
                    quantity=_safe_int(item.get("netqty")),
                    average_price=_safe_float(item.get("netavgprice")),
                    ltp=_safe_float(item.get("ltp")),
                    pnl=_safe_float(item.get("pnl")),
                )
                for item in items
            ]
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_positions() failed")
            raise BrokerAPIError(f"get_positions failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_order_book(self) -> list[Order]:
        """Return all orders for the current session."""
        self._require_connection()
        try:
            resp = self._smart.orderBook()
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_order_book failed: {resp}")
            items = resp.get("data") or []
            return [
                Order(
                    order_id=item.get("orderid", ""),
                    symbol=item.get("tradingsymbol", ""),
                    exchange=item.get("exchange", ""),
                    side=item.get("transactiontype", ""),
                    order_type=item.get("ordertype", ""),
                    quantity=_safe_int(item.get("quantity")),
                    price=_safe_float(item.get("price")),
                    status=item.get("status", ""),
                    timestamp=_parse_datetime(item.get("updatetime", "")),
                )
                for item in items
            ]
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_order_book() failed")
            raise BrokerAPIError(f"get_order_book failed: {exc}") from exc

    def place_order(
        self,
        instrument: Instrument,
        side: str,
        order_type: str,
        quantity: int,
        price: float,
    ) -> str:
        """Place an order. Returns the broker order_id."""
        self._require_connection()
        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": instrument.symbol,
                "symboltoken": instrument.token,
                "transactiontype": side.upper(),
                "exchange": instrument.exchange,
                "ordertype": order_type.upper(),
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": str(price),
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(quantity),
            }
            resp = self._smart.placeOrder(order_params)
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"place_order failed: {resp}")
            order_id = resp.get("data", {}).get("orderid", "")
            logger.info("Order placed: %s %s x%d → order_id=%s", side, instrument.symbol, quantity, order_id)
            return order_id
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.place_order() failed")
            raise BrokerAPIError(f"place_order failed: {exc}") from exc

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by order_id. Defaults to NORMAL variety."""
        self._require_connection()
        try:
            resp = self._smart.cancelOrder("NORMAL", order_id)
            if not resp or not resp.get("status"):
                logger.warning("cancel_order returned non-success: %s", resp)
                return False
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as exc:
            logger.exception("AngelBroker.cancel_order() failed")
            raise BrokerAPIError(f"cancel_order failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_ltp(self, exchange: str, token: str) -> float:
        """Return last traded price.

        Note: Angel's ltpData requires trading symbol as well as token.
        We pass token as the symbol here as a fallback — this works if
        the caller passes the symbol in the token field for LTP lookups.
        Use the MarketFeed (Phase 4) for real-time LTP where possible.
        """
        self._require_connection()
        try:
            resp = self._smart.ltpData(exchange, token, token)
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_ltp failed: {resp}")
            return _safe_float(resp.get("data", {}).get("ltp"))
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_ltp() failed")
            raise BrokerAPIError(f"get_ltp failed: {exc}") from exc

    def search_instruments(self, query: str) -> list[Instrument]:
        """Search instruments via local instrument master (preferred).

        Falls back to Angel searchScrip API if the master is not loaded.
        """
        from broker.instrument_master import InstrumentMaster
        if InstrumentMaster.is_loaded():
            return InstrumentMaster.search(query)

        # Fallback: live API search
        self._require_connection()
        results: list[Instrument] = []
        try:
            for exchange in ("NSE", "BSE", "NFO", "MCX"):
                resp = self._smart.searchScrip(exchange, query)
                if not resp or not resp.get("status"):
                    continue
                for item in resp.get("data") or []:
                    results.append(
                        Instrument(
                            symbol=item.get("tradingsymbol", ""),
                            token=item.get("symboltoken", ""),
                            exchange=item.get("exchange", exchange),
                            name=item.get("name", item.get("tradingsymbol", "")),
                            instrument_type=item.get("instrumenttype", ""),
                        )
                    )
            return results
        except Exception as exc:
            logger.exception("AngelBroker.search_instruments() failed")
            raise BrokerAPIError(f"search_instruments failed: {exc}") from exc

    def get_historical_data(
        self,
        exchange: str,
        token: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        """Fetch OHLCV candle data. interval e.g. 'ONE_MINUTE', 'ONE_DAY'."""
        self._require_connection()
        try:
            params = {
                "exchange": exchange,
                "symboltoken": token,
                "interval": interval,
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": to_date.strftime("%Y-%m-%d %H:%M"),
            }
            resp = self._smart.getCandleData(params)
            if not resp or not resp.get("status"):
                raise BrokerAPIError(f"get_historical_data failed: {resp}")
            candles = resp.get("data") or []
            return [
                {
                    "timestamp": c[0],
                    "open": _safe_float(c[1]),
                    "high": _safe_float(c[2]),
                    "low": _safe_float(c[3]),
                    "close": _safe_float(c[4]),
                    "volume": _safe_int(c[5]),
                }
                for c in candles
                if len(c) >= 6
            ]
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_historical_data() failed")
            raise BrokerAPIError(f"get_historical_data failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> None:
        if not self._is_connected or self._smart is None:
            raise BrokerAPIError("Not connected. Call connect() first.")


def _parse_datetime(value: str) -> datetime:
    """Parse Angel order timestamp strings. Falls back to epoch on failure."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            pass
    return datetime.fromtimestamp(0)
