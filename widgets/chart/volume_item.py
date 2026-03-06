from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

_DTYPE = np.dtype([
    ('t',  np.float64),  # unix timestamp
    ('v',  np.float64),  # volume
    ('up', np.bool_),    # True if close >= open
])

_COLOR_UP   = QColor('#1a3a2a')
_COLOR_DOWN = QColor('#3a1a1a')


class VolumeItem(pg.GraphicsObject):
    """Volume bar chart item for the lower pane.

    Mirrors the ``OHLCItem`` pattern: direct ``paint()`` drawing,
    cached ``boundingRect()``, and the same ``set_data`` / ``update_last_bar``
    / ``append_bar`` API.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: np.ndarray = np.empty(0, dtype=_DTYPE)
        self._bar_width: float = 0.6
        self._bounding_rect: QRectF = QRectF(0, 0, 1, 1)

    # ------------------------------------------------------------------
    # Data API
    # ------------------------------------------------------------------

    def set_data(self, data: np.ndarray) -> None:
        """Replace entire dataset. *data* must match ``_DTYPE``."""
        self._data = data
        self._update_bar_width()
        self._recompute_bounding_rect()
        self.prepareGeometryChange()
        self.update()

    def set_bar_width(self, bar_width: float) -> None:
        """Sync bar width from OHLCItem so both panes align."""
        self._bar_width = bar_width
        self._recompute_bounding_rect()
        self.update()

    def update_last_bar(self, v: float, up: bool) -> None:
        """Update volume of the last bar."""
        if len(self._data) == 0:
            return
        old_rect = QRectF(self._bounding_rect)
        self._data[-1]['v'] = v
        self._data[-1]['up'] = up
        self._recompute_bounding_rect()
        if self._bounding_rect != old_rect:
            self.prepareGeometryChange()
        self.update()

    def append_bar(self, t: float, v: float, up: bool) -> None:
        """Append a new volume bar."""
        new_row = np.array([(t, v, up)], dtype=_DTYPE)
        self._data = np.concatenate([self._data, new_row])
        self._recompute_bounding_rect()
        self.prepareGeometryChange()
        self.update()

    # ------------------------------------------------------------------
    # GraphicsObject contract
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        return self._bounding_rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if len(self._data) == 0:
            return

        exposed = option.exposedRect
        half_w = self._bar_width / 2

        for row in self._data:
            t  = float(row['t'])
            v  = float(row['v'])
            up = bool(row['up'])

            if t + half_w < exposed.left() or t - half_w > exposed.right():
                continue

            color = _COLOR_UP if up else _COLOR_DOWN
            painter.fillRect(QRectF(t - half_w, 0.0, self._bar_width, v), color)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_bar_width(self) -> None:
        if len(self._data) < 2:
            self._bar_width = 0.6
            return
        spacing = np.median(np.diff(self._data['t']))
        self._bar_width = float(spacing) * 0.6

    def _recompute_bounding_rect(self) -> None:
        if len(self._data) == 0:
            self._bounding_rect = QRectF(0, 0, 1, 1)
            return

        t_min = float(self._data['t'].min())
        t_max = float(self._data['t'].max())
        v_max = float(self._data['v'].max()) if len(self._data) > 0 else 1.0
        padding = v_max * 0.05 if v_max > 0 else 1.0

        self._bounding_rect = QRectF(
            t_min - self._bar_width,
            0.0,
            (t_max - t_min) + self._bar_width * 2,
            v_max + padding,
        )
