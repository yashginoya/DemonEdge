from abc import ABC, abstractmethod
from datetime import datetime

from models.instrument import Instrument
from models.order import Order
from models.position import Position


class BrokerAPIError(Exception):
    """Raised by broker implementations when an API call fails.

    Callers catch this one type instead of SDK-specific exceptions.
    """


class BaseBroker(ABC):
    """Abstract base class defining the broker interface.

    All broker interactions in the app go through this interface.
    Never import or call a concrete broker class outside of broker/.
    """

    @property
    @abstractmethod
    def broker_key(self) -> str:
        """Short identifier for this broker, e.g. 'angel'. Used for cache file naming."""
        ...

    @property
    @abstractmethod
    def instrument_master_url(self) -> str:
        """URL to download the full instrument master JSON (no auth required)."""
        ...

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate and establish a session. Returns True on success."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the session and release resources."""
        ...

    @abstractmethod
    def get_profile(self) -> dict:
        """Return the logged-in user's profile information."""
        ...

    @abstractmethod
    def get_holdings(self) -> list[Position]:
        """Return the user's equity holdings as a list of Position objects."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return intraday/overnight positions as a list of Position objects."""
        ...

    @abstractmethod
    def get_order_book(self) -> list[Order]:
        """Return all orders placed in the current session."""
        ...

    @abstractmethod
    def place_order(self, order_params: dict) -> str:
        """Place an order using a raw broker parameter dict.

        The dict keys match the Angel SmartAPI ``placeOrder`` format.
        Required keys: ``variety``, ``tradingsymbol``, ``symboltoken``,
        ``transactiontype``, ``exchange``, ``ordertype``, ``producttype``,
        ``duration``, ``price``, ``quantity``.
        Optional: ``triggerprice``, ``squareoff``, ``stoploss``,
        ``trailingStopLoss``.
        Returns the broker-assigned order_id string.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by order_id. Returns True if cancellation was accepted."""
        ...

    @abstractmethod
    def get_ltp(self, exchange: str, token: str) -> float:
        """Return the last traded price for a given exchange + token."""
        ...

    @abstractmethod
    def get_quote(self, exchange: str, token: str) -> dict:
        """Return a snapshot quote for a single instrument.

        Returns a dict with at least:
            ``ltp``        — last traded price (float)
            ``prev_close`` — previous session's closing price (float)

        Raises ``BrokerAPIError`` on failure.
        """
        ...

    @abstractmethod
    def search_instruments(self, query: str) -> list[Instrument]:
        """Search instruments by name/symbol. Returns matching Instrument objects."""
        ...

    @abstractmethod
    def get_order_margin(self, margin_params: dict) -> float:
        """Return the margin required for an order in rupees.

        ``margin_params`` keys: ``exchange``, ``tradingsymbol``, ``symboltoken``,
        ``transactiontype``, ``ordertype``, ``producttype``, ``variety``,
        ``quantity`` (str), ``price`` (str).
        Raises ``BrokerAPIError`` on failure.
        """
        ...

    @abstractmethod
    def get_historical_data(
        self,
        exchange: str,
        token: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[dict]:
        """Fetch OHLCV historical data. Returns a list of dicts with OHLCV keys."""
        ...

    @abstractmethod
    def get_index_info(self, symbol: str) -> dict | None:
        """Return the broker token and exchange for a well-known index symbol.

        Returns a dict with keys ``"token"`` (str) and ``"exchange"`` (str),
        or ``None`` if the symbol is not a recognised index for this broker.

        Example::

            broker.get_index_info("NIFTY")   # → {"token": "26000", "exchange": "NSE"}
            broker.get_index_info("SENSEX")  # → {"token": "1",     "exchange": "BSE"}
            broker.get_index_info("RELIANCE") # → None  (not an index)
        """
        ...
