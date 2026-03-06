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
    def place_order(
        self,
        instrument: Instrument,
        side: str,
        order_type: str,
        quantity: int,
        price: float,
    ) -> str:
        """Place an order. Returns the broker-assigned order_id string."""
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
    def search_instruments(self, query: str) -> list[Instrument]:
        """Search instruments by name/symbol. Returns matching Instrument objects."""
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
