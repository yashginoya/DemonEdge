from broker.base_broker import BaseBroker


class _BrokerManager:
    """Singleton managing the active broker instance."""

    _instance: "_BrokerManager | None" = None
    _broker: BaseBroker | None = None

    def __new__(cls) -> "_BrokerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_broker(self, broker: BaseBroker) -> None:
        """Register the active broker implementation."""
        self._broker = broker

    def get_broker(self) -> BaseBroker:
        """Return the active broker. Raises RuntimeError if no broker is set."""
        if self._broker is None:
            raise RuntimeError(
                "No broker set. Call BrokerManager.set_broker() first."
            )
        return self._broker

    def create_broker(self, broker_name: str, credentials: dict) -> BaseBroker:
        """Factory: instantiate the named broker, register it, and return it.

        Args:
            broker_name: "angel" (only supported option for now).
            credentials: dict with keys api_key, client_id, password, totp_secret.

        Raises:
            ValueError: if broker_name is not recognised.
        """
        if broker_name == "angel":
            from broker.angel_broker import AngelBroker
            broker: BaseBroker = AngelBroker(credentials)
        else:
            raise ValueError(f"Unknown broker: {broker_name!r}. Supported: 'angel'")
        self.set_broker(broker)
        return broker


BrokerManager = _BrokerManager()
