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
            broker_name: "angel" or "kite".
            credentials: broker-specific credentials dict.
                angel → api_key, client_id, password, totp_secret.
                kite  → api_key, api_secret, [access_token, access_token_date].

        Raises:
            ValueError: if broker_name is not recognised.
        """
        if broker_name == "angel":
            from broker.angel_broker import AngelBroker
            broker: BaseBroker = AngelBroker(credentials)
        elif broker_name == "kite":
            from broker.kite_broker import KiteBroker
            broker = KiteBroker(credentials)
        else:
            raise ValueError(
                f"Unknown broker: {broker_name!r}. Supported: 'angel', 'kite'"
            )
        self.set_broker(broker)
        return broker


BrokerManager = _BrokerManager()
