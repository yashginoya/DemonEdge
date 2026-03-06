from PySide6.QtCore import QObject, Signal


class MarketFeedSignals(QObject):
    """Qt signal bridge for MarketFeed (which is not a QObject itself).

    MarketFeed holds a lazy instance of this class. Connect to these signals
    from the main thread to receive feed lifecycle events and tick notifications.

    All signals are delivered on the Qt main thread via Qt's queued connection
    mechanism even though they are emitted from the daemon feed thread.
    """

    # Emitted when the WebSocket handshake completes
    feed_connected = Signal()

    # Emitted when the WebSocket connection is closed (graceful or unexpected)
    feed_disconnected = Signal()

    # Emitted on WebSocket error; carries a human-readable error message
    feed_error = Signal(str)

    # Emitted for every parsed tick — for debug/status widgets only.
    # High-frequency: do NOT connect heavy UI updates to this signal directly.
    tick_received = Signal(object)  # object = Tick
