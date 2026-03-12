from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QMainWindow

from utils.logger import get_logger

if TYPE_CHECKING:
    from widgets.base_widget import BaseWidget

logger = get_logger(__name__)

_LAYOUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "layout.json"
)
_FORMAT_VERSION = 1


class _LayoutManager:
    """Handles serialisation and restoration of the dock layout.

    Save format (config/layout.json):
    {
        "version": 1,
        "saved_at": "2024-01-15T10:30:00",
        "qt_state": "<base64 QMainWindow.saveState()>",
        "widgets": [
            {"instance_id": "watchlist_0", "widget_id": "watchlist", "state": {}}
        ]
    }
    """

    _instance: "_LayoutManager | None" = None

    def __new__(cls) -> "_LayoutManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def has_saved_layout(self) -> bool:
        return os.path.exists(_LAYOUT_PATH)

    def save(
        self,
        main_window: QMainWindow,
        widgets: list["BaseWidget"],
        detached_geometries: "dict | None" = None,
    ) -> None:
        """Serialise dock geometry and each widget's state to layout.json.

        Parameters
        ----------
        detached_geometries:
            Optional mapping of ``instance_id → QRect`` for widgets that are
            currently shown in a DetachedWindow.  When provided, each detached
            widget's geometry is persisted so it can be re-opened in the same
            position on the next session.

        Written atomically: temp file → rename.
        """
        qt_bytes: QByteArray = main_window.saveState()
        qt_state_b64 = base64.b64encode(bytes(qt_bytes)).decode("ascii")

        widget_entries = []
        for w in widgets:
            try:
                state = w.save_state()
            except Exception:
                logger.exception("save_state() failed for %s — using empty state", w.instance_id)
                state = {}
            entry: dict = {
                "instance_id": w.instance_id,
                "widget_id": w.widget_id,
                "state": state,
            }
            if detached_geometries and w.instance_id in detached_geometries:
                geo = detached_geometries[w.instance_id]
                entry["detached_geometry"] = [geo.x(), geo.y(), geo.width(), geo.height()]
            widget_entries.append(entry)

        data = {
            "version": _FORMAT_VERSION,
            "saved_at": datetime.now().isoformat(),
            "qt_state": qt_state_b64,
            "widgets": widget_entries,
        }

        os.makedirs(os.path.dirname(_LAYOUT_PATH), exist_ok=True)
        tmp_path = _LAYOUT_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, _LAYOUT_PATH)
        logger.info("Layout saved (%d widgets)", len(widgets))

    def restore(
        self, main_window: QMainWindow
    ) -> "tuple[list[BaseWidget], dict[str, list[int]]]":
        """Restore widgets and dock geometry from layout.json.

        For each widget entry: creates instance via WidgetRegistry, restores state,
        adds to main_window. Then restores Qt dock geometry via restoreState().

        Returns
        -------
        (widgets, detached_geometries)
            ``widgets`` — list of restored BaseWidget instances (caller registers them).
            ``detached_geometries`` — mapping of ``instance_id → [x, y, w, h]`` for
            widgets that were detached when the layout was saved.  The caller is
            responsible for re-opening those DetachedWindows.
        """
        if not self.has_saved_layout():
            return [], {}

        from app.widget_registry import WidgetRegistry

        try:
            with open(_LAYOUT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.exception("Failed to read layout.json — starting fresh")
            return [], {}

        if data.get("version", 0) != _FORMAT_VERSION:
            logger.warning(
                "layout.json version mismatch (got %s, expected %s) — skipping restore",
                data.get("version"),
                _FORMAT_VERSION,
            )
            return [], {}

        widgets: list[BaseWidget] = []
        detached_geometries: dict[str, list[int]] = {}

        from PySide6.QtWidgets import QDockWidget

        for entry in data.get("widgets", []):
            widget_id = entry.get("widget_id", "")
            instance_id = entry.get("instance_id", widget_id)
            state = entry.get("state", {})

            try:
                widget = WidgetRegistry.create(widget_id)

                # Standalone windows (e.g. MarketDepthWindow) are plain QWidgets,
                # not QDockWidgets.  Skip dock integration for them — they are
                # re-opened by MainWindow via their own launch path (e.g. F5).
                if not isinstance(widget, QDockWidget):
                    logger.debug(
                        "Skipping dock restore for standalone widget %r", widget_id
                    )
                    widget.deleteLater()
                    continue

                widget.instance_id = instance_id
                widget.setObjectName(instance_id)
                try:
                    widget.restore_state(state)
                except Exception:
                    logger.exception("restore_state() failed for %s", instance_id)
                main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, widget)
                widgets.append(widget)

                # Record detach geometry if present
                geo = entry.get("detached_geometry")
                if isinstance(geo, list) and len(geo) == 4:
                    detached_geometries[instance_id] = geo

            except KeyError:
                logger.warning("Unknown widget_id %r in layout.json — skipping", widget_id)
            except Exception:
                logger.exception("Failed to restore widget %s", instance_id)

        qt_state_b64 = data.get("qt_state", "")
        if qt_state_b64 and widgets:
            try:
                qt_bytes = QByteArray(base64.b64decode(qt_state_b64))
                main_window.restoreState(qt_bytes)
            except Exception:
                logger.exception("Failed to restore Qt dock state")

        logger.info("Layout restored (%d widgets)", len(widgets))
        return widgets, detached_geometries


LayoutManager = _LayoutManager()
