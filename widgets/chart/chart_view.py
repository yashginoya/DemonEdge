from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QWidget

from widgets.chart.ohlc_item import OHLCItem
from widgets.chart.volume_item import VolumeItem

_IST = ZoneInfo("Asia/Kolkata")
_OHLCV_FONT = QFont("Courier New", 8)

# How many bars to show in the initial view
_VISIBLE_BARS = 100


class _TimeAxisItem(pg.AxisItem):
    """Custom bottom axis that formats unix timestamps as time strings."""

    def tickStrings(self, values, scale, spacing):
        result = []
        for v in values:
            try:
                dt = datetime.fromtimestamp(v, tz=_IST)
                label = dt.strftime('%H:%M') if spacing < 86400 else dt.strftime('%d %b')
            except (OSError, OverflowError, ValueError):
                label = ''
            result.append(label)
        return result


class ChartView(QWidget):
    """pyqtgraph chart with price (OHLC) and volume panes.

    Signals
    -------
    bar_hovered(t, o, h, l, c, v, symbol)
        Emitted on mouse move when cursor is over a bar. ``t`` is unix float.
        ``symbol`` is the instrument symbol string.
    """

    bar_hovered = Signal(float, float, float, float, float, float, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._symbol: str = ""
        self._auto_scroll: bool = True
        self._last_t_max: float = 0.0   # rightmost bar timestamp after last append

        self._build_layout()
        self._add_items()
        self._setup_crosshair()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.glw = pg.GraphicsLayoutWidget()

        # Price plot — custom bottom axis hidden (shown on volume plot only)
        self.price_plot: pg.PlotItem = self.glw.addPlot(row=0, col=0)
        self.glw.nextRow()

        # Volume plot — custom time axis
        time_axis = _TimeAxisItem(orientation='bottom')
        self.volume_plot: pg.PlotItem = self.glw.addPlot(row=1, col=0, axisItems={'bottom': time_axis})

        # Row stretch
        self.glw.ci.layout.setRowStretchFactor(0, 7)
        self.glw.ci.layout.setRowStretchFactor(1, 3)

        # Price plot style
        self.price_plot.setMenuEnabled(False)
        self.price_plot.showGrid(x=True, y=True, alpha=0.15)
        self.price_plot.getAxis('left').setStyle(tickFont=_OHLCV_FONT)
        self.price_plot.getAxis('bottom').setStyle(showValues=False)
        self.price_plot.setLabel('left', '', units='₹')

        # Volume plot style
        self.volume_plot.setMenuEnabled(False)
        self.volume_plot.showGrid(x=False, y=False)
        self.volume_plot.getAxis('bottom').setStyle(tickFont=_OHLCV_FONT)
        self.volume_plot.setMaximumHeight(120)
        self.volume_plot.getAxis('left').setStyle(tickFont=_OHLCV_FONT)

        # Link x-axes
        self.volume_plot.setXLink(self.price_plot)

        layout.addWidget(self.glw)

    def _add_items(self) -> None:
        self.ohlc_item   = OHLCItem()
        self.volume_item = VolumeItem()
        self.price_plot.addItem(self.ohlc_item)
        self.volume_plot.addItem(self.volume_item)

        # OHLCV info label anchored to top-left of price plot
        self._info_label = pg.LabelItem(
            text="",
            color="#8b949e",
            size="9pt",
            parent=self.price_plot.getViewBox(),
        )
        self._info_label.anchor(itemPos=(0, 0), parentPos=(0, 0), offset=(5, 5))

    def _setup_crosshair(self) -> None:
        dash = Qt.PenStyle.DashLine
        self.vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('#8b949e', width=1, style=dash)
        )
        self.hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('#8b949e', width=1, style=dash)
        )
        self.price_plot.addItem(self.vline, ignoreBounds=True)
        self.price_plot.addItem(self.hline, ignoreBounds=True)

    def _connect_signals(self) -> None:
        self.price_plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.price_plot.sigRangeChanged.connect(self._on_range_changed)

    # ------------------------------------------------------------------
    # Data updates
    # ------------------------------------------------------------------

    def set_data(self, ohlc_array: np.ndarray, volume_array: np.ndarray) -> None:
        """Load a full historical dataset and auto-range the view."""
        self.ohlc_item.set_data(ohlc_array)
        self.volume_item.set_data(volume_array)
        self.volume_item.set_bar_width(self.ohlc_item._bar_width)

        if len(ohlc_array) == 0:
            return

        self._last_t_max = float(ohlc_array['t'].max())
        self._scroll_to_right()
        self._auto_scroll = True

    def update_last_bar(self, t: float, o: float, h: float, l: float, c: float, v: float) -> None:
        """Update the rightmost bar with new tick data."""
        self.ohlc_item.update_last_bar(o, h, l, c, t)
        self.volume_item.update_last_bar(v, c >= o)

    def append_bar(self, t: float, o: float, h: float, l: float, c: float, v: float) -> None:
        """Add a new bar (new time period has started)."""
        self.ohlc_item.append_bar(o, h, l, c, t)
        self.volume_item.append_bar(t, v, c >= o)
        self.volume_item.set_bar_width(self.ohlc_item._bar_width)
        self._last_t_max = t
        if self._auto_scroll:
            self._scroll_to_right()

    def set_symbol(self, symbol: str) -> None:
        self._symbol = symbol

    # ------------------------------------------------------------------
    # View helpers
    # ------------------------------------------------------------------

    def _scroll_to_right(self) -> None:
        """Pan the x-range to show the latest _VISIBLE_BARS bars."""
        bw = self.ohlc_item._bar_width
        spacing = bw / 0.6  # recover bar spacing from bar_width fraction
        if spacing <= 0:
            spacing = 60

        x_max = self._last_t_max + bw
        x_min = x_max - spacing * _VISIBLE_BARS
        self.price_plot.setXRange(x_min, x_max, padding=0)

    def _on_range_changed(self, view_box, ranges) -> None:
        """Detect user panning left — disable auto-scroll; at right edge — re-enable."""
        if len(self.ohlc_item._data) == 0:
            return
        x_range = ranges[0]
        # If the right edge of current view is within 3 bars of the latest bar → auto-scroll on
        bw = self.ohlc_item._bar_width
        spacing = bw / 0.6 if bw > 0 else 60
        near_right = x_range[1] >= (self._last_t_max - spacing * 3)
        self._auto_scroll = near_right

    # ------------------------------------------------------------------
    # Mouse / crosshair
    # ------------------------------------------------------------------

    def _on_mouse_moved(self, pos) -> None:
        if not self.price_plot.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.price_plot.getViewBox().mapSceneToView(pos)
        mx = mouse_point.x()
        my = mouse_point.y()

        self.vline.setPos(mx)
        self.hline.setPos(my)

        # Find nearest bar
        data = self.ohlc_item._data
        if len(data) == 0:
            return

        idx = int(np.argmin(np.abs(data['t'] - mx)))
        bar = data[idx]
        t, o, h, l, c = float(bar['t']), float(bar['o']), float(bar['h']), float(bar['l']), float(bar['c'])

        # Fetch volume from volume item
        vdata = self.volume_item._data
        v = 0.0
        if idx < len(vdata):
            v = float(vdata[idx]['v'])

        # Update info label
        dt_str = datetime.fromtimestamp(t, tz=_IST).strftime('%d %b %H:%M')
        color_o = "#e6edf3"
        color_c = "#3fb950" if c >= o else "#f85149"
        self._info_label.setText(
            f"<span style='color:#8b949e'>{self._symbol}  {dt_str}</span>  "
            f"<span style='color:{color_o}'>O:{o:.2f}  H:{h:.2f}  L:{l:.2f}</span>  "
            f"<span style='color:{color_c}'>C:{c:.2f}</span>  "
            f"<span style='color:#8b949e'>V:{int(v):,}</span>"
        )

        self.bar_hovered.emit(t, o, h, l, c, v, self._symbol)
