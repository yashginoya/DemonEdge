"""FeedManager — singleton that provides the active BaseFeed instance.

Mirrors BrokerManager in broker/broker_manager.py.

Usage::

    from feed.feed_manager import FeedManager

    # Subscribe to a symbol
    FeedManager.get_feed().subscribe("NSE", "2885", my_callback, SubscriptionMode.LTP)

    # Connect / disconnect the feed
    FeedManager.get_feed().connect(broker)
    FeedManager.get_feed().disconnect()

The default feed (AngelFeed) is registered automatically when
``feed.market_feed`` is first imported.  You only need to call
``FeedManager.set_feed()`` explicitly when swapping to a different
feed implementation.
"""

from __future__ import annotations

from feed.base_feed import BaseFeed


class _FeedManager:
    """Singleton managing the active feed implementation."""

    _instance: "_FeedManager | None" = None
    _feed: BaseFeed | None = None

    def __new__(cls) -> "_FeedManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_feed(self, feed: BaseFeed) -> None:
        """Register the active feed implementation."""
        self._feed = feed

    def get_feed(self) -> BaseFeed:
        """Return the active feed.

        If no feed has been explicitly set, imports ``feed.market_feed`` to
        trigger auto-registration of the default AngelFeed singleton.

        Raises RuntimeError if feed initialisation fails.
        """
        if self._feed is None:
            # Lazy default: importing market_feed registers AngelFeed with us.
            import feed.market_feed  # noqa: F401 — side-effect import
        if self._feed is None:
            raise RuntimeError(
                "No feed set.  Import feed.market_feed or call FeedManager.set_feed() first."
            )
        return self._feed


FeedManager = _FeedManager()
