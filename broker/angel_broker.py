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
            resp = self._parse_response(
                self._smart.getProfile(self._refresh_token), "get_profile"
            )
            if not resp.get("status"):
                raise BrokerAPIError(f"get_profile failed: {resp.get('message', resp)}")
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
            resp = self._parse_response(self._smart.holding(), "get_holdings")
            if not resp.get("status"):
                raise BrokerAPIError(f"get_holdings failed: {resp.get('message', resp)}")
            items = resp.get("data") or []
            return [
                Position(
                    symbol=item.get("tradingsymbol", ""),
                    token=item.get("symboltoken", ""),
                    exchange=item.get("exchange", ""),
                    product_type="DELIVERY",
                    quantity=_safe_int(item.get("quantity")),
                    average_price=_safe_float(item.get("averageprice")),
                    ltp=_safe_float(item.get("ltp")),
                    realized_pnl=_safe_float(item.get("profitandloss")),
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
            resp = self._parse_response(self._smart.position(), "get_positions")
            if not resp.get("status"):
                raise BrokerAPIError(f"get_positions failed: {resp.get('message', resp)}")
            items = resp.get("data") or []
            positions = []
            for item in items:
                qty = _safe_int(item.get("netqty"))
                avg = _safe_float(item.get("netavgprice"))
                ltp = _safe_float(item.get("ltp"))
                realized = _safe_float(item.get("pnl"))
                unrealized = (ltp - avg) * qty if qty != 0 else 0.0
                positions.append(Position(
                    symbol=item.get("tradingsymbol", ""),
                    token=item.get("symboltoken", ""),
                    exchange=item.get("exchange", ""),
                    product_type=item.get("producttype", ""),
                    quantity=qty,
                    overnight_quantity=_safe_int(item.get("overnightquantity", 0)),
                    buy_quantity=_safe_int(item.get("buyqty")),
                    sell_quantity=_safe_int(item.get("sellqty")),
                    average_price=avg,
                    buy_average=_safe_float(item.get("buyavgprice")),
                    sell_average=_safe_float(item.get("sellavgprice")),
                    ltp=ltp,
                    close_price=_safe_float(item.get("close")),
                    realized_pnl=realized,
                    unrealized_pnl=unrealized,
                    total_pnl=unrealized + realized,
                ))
            return positions
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
            resp = self._parse_response(self._smart.orderBook(), "get_order_book")
            if not resp.get("status"):
                raise BrokerAPIError(f"get_order_book failed: {resp.get('message', resp)}")
            items = resp.get("data") or []
            return [
                Order(
                    order_id=item.get("orderid", ""),
                    symbol=item.get("tradingsymbol", ""),
                    token=item.get("symboltoken", ""),
                    exchange=item.get("exchange", ""),
                    side=item.get("transactiontype", ""),
                    order_type=item.get("ordertype", ""),
                    product_type=item.get("producttype", ""),
                    variety=item.get("variety", ""),
                    quantity=_safe_int(item.get("quantity")),
                    price=_safe_float(item.get("price")),
                    trigger_price=_safe_float(item.get("triggerprice")),
                    status=item.get("status", ""),
                    status_message=item.get("text", ""),
                    timestamp=_parse_datetime(item.get("updatetime", "")),
                    filled_quantity=_safe_int(item.get("filledshares")),
                    average_price=_safe_float(item.get("averageprice")),
                )
                for item in items
            ]
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_order_book() failed")
            raise BrokerAPIError(f"get_order_book failed: {exc}") from exc

    def place_order(self, order_params: dict) -> str:
        """Place an order using raw parameter dict. Returns the broker order_id."""
        self._require_connection()
        try:
            raw = self._smart.placeOrder(order_params)
            logger.debug("place_order raw response type=%s value=%r", type(raw).__name__, raw)
            resp = self._parse_response(raw, "place_order")

            if not resp.get("status"):
                error_msg = resp.get("message", "Unknown error")
                error_code = resp.get("errorcode", "")
                raise BrokerAPIError(
                    f"place_order failed: {error_msg}"
                    + (f" (code: {error_code})" if error_code else "")
                )

            data = resp.get("data", {})
            if isinstance(data, dict):
                order_id = data.get("orderid", "")
            elif isinstance(data, str):
                # Angel sometimes returns the order ID as the data value directly
                order_id = data
            else:
                order_id = str(data) if data else ""

            logger.info(
                "Order placed: %s %s x%s → order_id=%s",
                order_params.get("transactiontype"),
                order_params.get("tradingsymbol"),
                order_params.get("quantity"),
                order_id,
            )
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
            raw = self._smart.cancelOrder("NORMAL", order_id)
            resp = self._parse_response(raw, "cancel_order")
            if not resp.get("status"):
                logger.warning(
                    "cancel_order returned non-success: %s",
                    resp.get("message", resp),
                )
                return False
            logger.info("Order cancelled: %s", order_id)
            return True
        except BrokerAPIError:
            raise
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

    def get_order_margin(self, margin_params: dict) -> float:
        """Return margin required for an order in rupees.

        Calls Angel SmartAPI ``getMarginApi()`` (batch endpoint).
        Wraps ``margin_params`` in ``{"orders": [margin_params]}`` as required
        by the API.  The response ``data`` field is a list; we read the first
        element and extract the margin value.
        Raises ``BrokerAPIError`` on failure.
        """
        self._require_connection()
        try:
            # --- Pre-call normalisation ---
            # Work on a copy so the caller's dict is not mutated
            params = dict(margin_params)

            variety = params.get("variety", "NORMAL")
            product = params.get("producttype", "")

            # BRACKET/ROBO (BO) is only legal with INTRADAY
            if variety in ("ROBO", "BO") and product != "INTRADAY":
                logger.debug(
                    "get_order_margin: skipping — BRACKET/ROBO requires INTRADAY (got %s)", product
                )
                return 0.0

            # MARKET orders must send price "0" (not "0.0")
            if params.get("ordertype") == "MARKET":
                params["price"] = "0"
            else:
                # Ensure price is a clean decimal string
                try:
                    params["price"] = f"{float(params.get('price', '0')):.2f}"
                except (ValueError, TypeError):
                    params["price"] = "0"

            # Quantity must be a plain integer string
            try:
                params["quantity"] = str(int(float(params.get("quantity", "0"))))
            except (ValueError, TypeError):
                pass

            logger.debug("get_order_margin: sending params=%s", params)
            resp = self._smart.getMarginApi({"orders": [params]})
            logger.debug("get_order_margin: raw response=%s", resp)

            if not resp:
                raise BrokerAPIError("get_order_margin: empty response from API")
            if not resp.get("status"):
                msg = resp.get("message", "unknown error")
                logger.warning("get_order_margin: API returned failure — %s", msg)
                raise BrokerAPIError(f"get_order_margin failed: {msg}")

            data = resp.get("data")

            # Batch endpoint returns data as a list of per-order dicts
            if isinstance(data, list):
                if not data:
                    raise BrokerAPIError("get_order_margin: empty data list in response")
                data = data[0]

            # Scalar response (unlikely but handle it)
            if isinstance(data, (int, float, str)):
                return _safe_float(data)

            if isinstance(data, dict):
                # Try known keys in priority order
                for key in (
                    "totalMarginRequired",
                    "netMarginRequired",
                    "netMargin",
                    "marginRequired",
                    "margin",
                ):
                    if key in data:
                        return _safe_float(data[key])
                # Last resort: first non-negative numeric value in the dict
                for val in data.values():
                    f = _safe_float(val, default=-1.0)
                    if f >= 0:
                        return f

            raise BrokerAPIError(
                f"get_order_margin: unrecognised response shape — data={data!r}"
            )
        except BrokerAPIError:
            raise
        except Exception as exc:
            logger.exception("AngelBroker.get_order_margin() failed")
            raise BrokerAPIError(f"get_order_margin failed: {exc}") from exc

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

    def _parse_response(self, resp: object, method_name: str) -> dict:
        """Normalise an Angel API response to a dict.

        Angel SmartAPI occasionally returns a JSON *string* instead of a
        parsed dict (observed in placeOrder and orderBook).  This helper
        handles both shapes and raises ``BrokerAPIError`` for anything else.
        """
        if isinstance(resp, str):
            import json as _json
            try:
                resp = _json.loads(resp)
            except (ValueError, TypeError) as exc:
                raise BrokerAPIError(
                    f"{method_name}: unexpected string response: {resp!r}"
                ) from exc
        if not isinstance(resp, dict):
            raise BrokerAPIError(
                f"{method_name}: unexpected response type {type(resp).__name__}: {resp!r}"
            )
        return resp


def _parse_datetime(value: str) -> datetime:
    """Parse Angel order timestamp strings. Falls back to epoch on failure."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            pass
    return datetime.fromtimestamp(0)
