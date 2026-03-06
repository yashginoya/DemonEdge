from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainter

_DTYPE = np.dtype([
    ('t', np.float64),  # unix timestamp
    ('o', np.float64),  # open
    ('h', np.float64),  # high
    ('l', np.float64),  # low
    ('c', np.float64),  # close
])

_GREEN_PEN = pg.mkPen('#3fb950', width=1.5)
_RED_PEN   = pg.mkPen('#f85149', width=1.5)


class OHLCItem(pg.GraphicsObject):
    """Custom OHLC bar chart item for pyqtgraph.

    Each bar is rendered as:
    - A vertical line from low to high
    - A left horizontal tick at the open price
    - A right horizontal tick at the close price

    Uses direct ``paint()`` drawing (NOT QPicture) so that live updates via
    ``update()`` cause an immediate repaint without requiring user interaction.

    ``boundingRect()`` always returns a cached ``QRectF`` — it is never
    computed inside ``boundingRect()`` to avoid performance issues (pyqtgraph
    calls it very frequently during layout/zoom operations).
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

    def update_last_bar(self, o: float, h: float, l: float, c: float, t: float) -> None:
        """Update the last bar in-place (live tick in current period)."""
        if len(self._data) == 0:
            return
        old_rect = QRectF(self._bounding_rect)
        self._data[-1]['o'] = o
        self._data[-1]['h'] = h
        self._data[-1]['l'] = l
        self._data[-1]['c'] = c
        self._recompute_bounding_rect()
        if self._bounding_rect != old_rect:
            self.prepareGeometryChange()
        self.update()

    def append_bar(self, o: float, h: float, l: float, c: float, t: float) -> None:
        """Append a new completed (or opening) bar."""
        new_row = np.array([(t, o, h, l, c)], dtype=_DTYPE)
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
        tick_w = self._bar_width * 0.4

        for row in self._data:
            t, o, h, l, c = float(row['t']), float(row['o']), float(row['h']), float(row['l']), float(row['c'])

            # Skip bars completely outside the visible region
            if t + self._bar_width < exposed.left() or t - self._bar_width > exposed.right():
                continue

            pen = _GREEN_PEN if c >= o else _RED_PEN
            painter.setPen(pen)

            # Vertical wick: low → high
            painter.drawLine(QPointF(t, l), QPointF(t, h))
            # Open tick (left)
            painter.drawLine(QPointF(t - tick_w, o), QPointF(t, o))
            # Close tick (right)
            painter.drawLine(QPointF(t, c), QPointF(t + tick_w, c))

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
        low_min = float(self._data['l'].min())
        high_max = float(self._data['h'].max())

        height = high_max - low_min
        padding = height * 0.05 if height > 0 else 1.0

        self._bounding_rect = QRectF(
            t_min - self._bar_width,
            low_min - padding,
            (t_max - t_min) + self._bar_width * 2,
            height + padding * 2,
        )
