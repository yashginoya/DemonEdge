from models.instrument import Instrument


class _AppState:
    """Singleton holding global application state."""

    _instance: "_AppState | None" = None

    def __new__(cls) -> "_AppState":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._selected_instrument: Instrument | None = None
            cls._instance._is_connected: bool = False
        return cls._instance

    def set_selected_instrument(self, instrument: Instrument | None) -> None:
        self._selected_instrument = instrument

    def get_selected_instrument(self) -> Instrument | None:
        return self._selected_instrument

    def set_connected(self, connected: bool) -> None:
        self._is_connected = connected

    def is_connected(self) -> bool:
        return self._is_connected


AppState = _AppState()
