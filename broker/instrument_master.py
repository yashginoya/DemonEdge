"""InstrumentMaster — local instrument cache for fast symbol search.

Downloads the broker's full instrument list once per day and stores it as
``data/instrument_master/{broker_key}_{YYYY-MM-DD}.json``.  Subsequent
calls within the same calendar day reuse the cached file — no network
request needed.

Usage::

    from broker.instrument_master import InstrumentMaster
    from broker.broker_manager import BrokerManager

    # On login (runs in a worker thread):
    count = InstrumentMaster.instance().ensure_loaded(BrokerManager.get_broker())

    # In SearchDialog (main thread — fast, in-memory):
    results = InstrumentMaster.instance().search("reliance", exchange="NSE")
    result  = InstrumentMaster.instance().get_by_token("NSE", "2885")
"""

from __future__ import annotations

import glob
import json
import os
import urllib.request
from datetime import date
from typing import TYPE_CHECKING

from models.instrument import Instrument
from utils.logger import get_logger

if TYPE_CHECKING:
    from broker.base_broker import BaseBroker

logger = get_logger(__name__)

# Project root — two levels up from this file (broker/instrument_master.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data", "instrument_master")


def _safe_float(val: object, default: float = 0.0) -> float:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_int(val: object, default: int = 0) -> int:
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


class _InstrumentMaster:
    """Singleton — access via ``InstrumentMaster.instance()``."""

    _instance: "_InstrumentMaster | None" = None

    def __new__(cls) -> "_InstrumentMaster":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
            cls._instance._index: list[tuple[str, str, dict]] = []
            cls._instance._token_map: dict[str, dict] = {}
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_loaded(self) -> bool:
        return self._loaded

    def record_count(self) -> int:
        return len(self._index)

    def ensure_loaded(self, broker: "BaseBroker") -> int:
        """Download today's instrument master if needed, build search index.

        Returns the total record count.
        Raises ``RuntimeError`` if no data could be loaded.
        """
        if self._loaded:
            return len(self._index)

        os.makedirs(_DATA_DIR, exist_ok=True)

        today_str = date.today().isoformat()
        today_file = os.path.join(_DATA_DIR, f"{broker.broker_key}_{today_str}.json")

        if os.path.exists(today_file):
            logger.info("Using cached instrument master: %s", today_file)
            self._load_from_file(today_file)
            return len(self._index)

        # Try to download fresh copy
        try:
            self._download(broker.instrument_master_url, today_file)
            self._load_from_file(today_file)
            return len(self._index)
        except Exception as exc:
            logger.warning("Failed to download instrument master: %s", exc)
            # Remove partial download if any
            if os.path.exists(today_file):
                try:
                    os.remove(today_file)
                except OSError:
                    pass

        # Fallback: use most recent cached file for this broker
        pattern = os.path.join(_DATA_DIR, f"{broker.broker_key}_*.json")
        existing = sorted(glob.glob(pattern), reverse=True)
        if existing:
            logger.info("Falling back to cached instrument master: %s", existing[0])
            self._load_from_file(existing[0])
            return len(self._index)

        raise RuntimeError(
            "Could not load instrument master: download failed and no cache available."
        )

    def search(
        self,
        query: str,
        exchange: str = "",
        max_results: int = 100,
    ) -> list[Instrument]:
        """Search instruments in memory.

        Scoring:
          3 — symbol starts with query
          2 — name starts with query
          1 — query appears anywhere in symbol or name

        Results are sorted by score descending, then symbol ascending.
        """
        if not self._loaded:
            return []

        q = query.lower().strip()
        if len(q) < 2:
            return []

        scored: list[tuple[int, str, dict]] = []
        for sym_lower, name_lower, record in self._index:
            if exchange and record.get("exch_seg", "") != exchange:
                continue

            if sym_lower.startswith(q):
                score = 3
            elif name_lower.startswith(q):
                score = 2
            elif q in sym_lower or q in name_lower:
                score = 1
            else:
                continue

            scored.append((score, sym_lower, record))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [self._to_instrument(r) for _, _, r in scored[:max_results]]

    def get_by_token(self, exchange: str, token: str) -> Instrument | None:
        """Look up a single instrument by exchange + token. O(1)."""
        record = self._token_map.get(f"{exchange}:{token}")
        if record is None:
            return None
        return self._to_instrument(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _download(self, url: str, dest_path: str) -> None:
        logger.info("Downloading instrument master from %s", url)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        logger.info(
            "Instrument master downloaded: %d bytes → %s", len(data), dest_path
        )

    def _load_from_file(self, path: str) -> None:
        logger.info("Loading instrument master from %s", path)
        with open(path, encoding="utf-8") as f:
            records: list[dict] = json.load(f)
        self._build_index(records)
        logger.info("Instrument master loaded: %d records", len(self._index))

    def _build_index(self, records: list[dict]) -> None:
        index: list[tuple[str, str, dict]] = []
        token_map: dict[str, dict] = {}

        for rec in records:
            sym = rec.get("symbol", "")
            name = rec.get("name", "")
            exch = rec.get("exch_seg", "")
            token = rec.get("token", "")

            index.append((sym.lower(), name.lower(), rec))

            if token and exch:
                token_map[f"{exch}:{token}"] = rec

        self._index = index
        self._token_map = token_map
        self._loaded = True

    def _to_instrument(self, record: dict) -> Instrument:
        # Angel tick_size is stored in paise (e.g. "5" = ₹0.05)
        tick_size = _safe_float(record.get("tick_size", "5")) / 100.0
        if tick_size <= 0.0:
            tick_size = 0.05

        return Instrument(
            symbol=record.get("symbol", ""),
            token=record.get("token", ""),
            exchange=record.get("exch_seg", ""),
            name=record.get("name", ""),
            instrument_type=record.get("instrumenttype", ""),
            expiry=record.get("expiry", ""),
            strike=_safe_float(record.get("strike", "-1")),
            lot_size=_safe_int(record.get("lotsize", "1")) or 1,
            tick_size=tick_size,
        )


# Module-level singleton — import and use directly
InstrumentMaster = _InstrumentMaster()
