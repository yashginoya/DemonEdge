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

    def create_feed(self, broker_key: str) -> BaseFeed:
        """Factory: select and register the feed matching the active broker.

        Mirrors ``BrokerManager.create_broker`` — call this on login so the
        active feed always matches the active broker.

        Args:
            broker_key: "angel" or "kite".

        Raises:
            ValueError: if broker_key is not recognised.
        """
        if broker_key == "angel":
            import feed.market_feed  # noqa: F401 — registers AngelFeed
            from feed.market_feed import AngelFeed
            feed: BaseFeed = AngelFeed()
        elif broker_key == "kite":
            from feed.kite_feed import KiteFeed
            feed = KiteFeed()
        else:
            raise ValueError(
                f"Unknown broker for feed: {broker_key!r}. Supported: 'angel', 'kite'"
            )
        self.set_feed(feed)
        return feed


FeedManager = _FeedManager()
