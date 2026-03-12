"""Abstract base class for the market data feed.

All feed interactions in the app go through this interface.
Never import or call a concrete feed class (AngelFeed, etc.) outside of feed/.

The canonical way to access the feed from anywhere in the app is::

    from feed.feed_manager import FeedManager
    feed = FeedManager.get_feed()
    feed.subscribe("NSE", "2885", my_callback, SubscriptionMode.LTP)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from feed.feed_models import SubscriptionMode
from models.tick import Tick


class BaseFeed(ABC):
    """Abstract interface for a live market data feed.

    Concrete implementations (e.g. AngelFeed) wrap a specific broker's
    WebSocket and must implement every method here.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, broker) -> None:
        """Start the feed using credentials from *broker*.

        *broker* must expose ``auth_token``, ``api_key``, ``client_code``,
        and ``feed_token`` properties (populated after ``BaseBroker.connect``).
        This method returns immediately; the feed runs on a daemon thread.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Close the feed connection and release resources."""
        ...

    # ------------------------------------------------------------------
    # Pub / sub
    # ------------------------------------------------------------------

    @abstractmethod
    def subscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
        mode: int = SubscriptionMode.LTP,
    ) -> None:
        """Register *callback* to receive tick updates for *exchange*:*token*.

        If the feed is not yet connected the subscription is queued and sent
        once the connection is established.  Callbacks are invoked on the
        **feed thread** — use Qt signals to cross to the main thread before
        touching any UI.
        """
        ...

    @abstractmethod
    def unsubscribe(
        self,
        exchange: str,
        token: str,
        callback: Callable[[Tick], None],
    ) -> None:
        """Remove *callback* from tick updates for *exchange*:*token*."""
        ...

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True when the underlying WebSocket connection is active."""
        ...

    @abstractmethod
    def subscriber_count(self) -> int:
        """Return the total number of active (key, callback) registrations."""
        ...

    # ------------------------------------------------------------------
    # Qt signal bridge
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def signals(self):
        """Return the Qt signal bridge object (``MarketFeedSignals``).

        Connect to ``signals.feed_connected``, ``signals.feed_disconnected``,
        ``signals.feed_error``, and ``signals.tick_received`` from the main
        thread to receive lifecycle and tick events.
        """
        ...
