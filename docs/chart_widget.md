# Chart Widget Reference

## Overview

`ChartWidget` (`widgets/chart/chart_widget.py`) is a live OHLC bar chart using
**pyqtgraph**. It fetches historical data from the broker REST API and updates
the current bar in real-time via `MarketFeed`.

## File Structure

```
widgets/chart/
├── timeframe.py          — Timeframe enum + TimeframeInfo metadata
├── ohlc_item.py          — pg.GraphicsObject: OHLC bar rendering
├── volume_item.py        — pg.GraphicsObject: volume bar rendering
├── chart_data_manager.py — async historical fetch + live tick aggregation
├── chart_view.py         — pyqtgraph layout, axes, crosshair, info label
└── chart_widget.py       — BaseWidget shell, toolbar, feed wiring
```

## pyqtgraph Dark Theme Config

Set these **before** `QApplication` is created (in `main.py`):

```python
import pyqtgraph as pg
pg.setConfigOption('background', '#0d1117')
pg.setConfigOption('foreground', '#8b949e')
pg.setConfigOption('antialias', True)
```

## OHLC Rendering: Direct `paint()` vs `QPicture`

pyqtgraph has no built-in OHLC item. Two approaches are possible:

| Approach | How | Live update | Used? |
|---|---|---|---|
| `QPicture` | Pre-render all bars into a `QPicture` object in `generatePicture()` | ❌ Only redraws on zoom/pan, not on data change | ❌ No |
| Direct `paint()` | Draw in `paint()` using `QPainter` primitives each frame | ✅ Redraws immediately on `update()` call | ✅ Yes |

**We use direct `paint()`**. After modifying bar data, call `self.update()` on the
graphics item — Qt schedules a repaint immediately on the next event loop iteration.

### `boundingRect()` caching rule

pyqtgraph calls `boundingRect()` very frequently during layout, zoom, and pan.
**Never compute it inside `boundingRect()`**. Instead:

```python
def boundingRect(self) -> QRectF:
    return self._bounding_rect   # always return cached value

def _recompute_bounding_rect(self) -> None:
    # ... expensive computation ...
    self._bounding_rect = QRectF(...)
```

Call `_recompute_bounding_rect()` only when data actually changes, and call
`prepareGeometryChange()` before assigning a new bounding rect.

## OHLC Bar Visual Style

Each bar:
- Vertical line from `low` to `high` (the range wick)
- Short horizontal tick to the **left** at `open` (open tick)
- Short horizontal tick to the **right** at `close` (close tick)
- Green (`#3fb950`) if `close >= open`, red (`#f85149`) if `close < open`
- Tick width = `bar_width × 0.4`

Bar width is auto-computed as `0.6 × median spacing between timestamps`.

## Data Format (numpy structured arrays)

```python
# OHLCItem dtype
np.dtype([('t', np.float64), ('o', np.float64), ('h', np.float64),
          ('l', np.float64), ('c', np.float64)])

# VolumeItem dtype
np.dtype([('t', np.float64), ('v', np.float64), ('up', np.bool_)])
```

The x-axis position `t` is a **unix timestamp float** (seconds since epoch).
Angel's historical API returns IST strings — `_parse_timestamp()` converts them.
Angel's historical prices are already in **rupees** (not paise).

## Bar Aggregation (ChartDataManager)

```
Live tick arrives (feed thread)
  → _tick_callback emits _tick_signal (Qt queued)
  → _on_tick_main(tick) on main thread
  → data_manager.on_tick(tick)
      → floor tick.exchange_timestamp to bar boundary
      → if same bar: update H/L/C/V, emit bar_updated
      → if new bar: append new bar, emit bar_appended
  → chart_view.update_last_bar() or chart_view.append_bar()
  → ohlc_item.update_last_bar() / ohlc_item.append_bar()
  → self.update() → Qt schedules repaint
```

**Bar boundary flooring** (`_get_bar_start`):

```python
def _get_bar_start(dt: datetime, tf: Timeframe) -> float:
    secs = tf.value.seconds
    return math.floor(dt.timestamp() / secs) * secs
```

Example: `10:17:32` floored to M5 → `10:15:00`.

## Auto-Scroll Behavior

`ChartView` tracks `_auto_scroll: bool`:

- **True** (default): after every `append_bar`, pan x-range right to show the last 100 bars.
- **False**: user has panned left to look at history — do NOT force-scroll.
- Switches back to **True** when the right edge of the view is within 3 bars of the latest bar.

Implementation:

```python
def _on_range_changed(self, view_box, ranges) -> None:
    x_range = ranges[0]
    near_right = x_range[1] >= (self._last_t_max - spacing * 3)
    self._auto_scroll = near_right
```

## Watchlist → Chart Integration

Right-click a watchlist row → "Add to Chart":

1. `WatchlistTab._add_to_chart(instrument)` gets `QApplication.activeWindow()`.
2. Calls `main_window.get_first_widget_of_type("chart")`.
3. Calls `chart._load_chart(instrument, chart._timeframe)` on the found chart.

`MainWindow.get_first_widget_of_type(widget_id)` iterates `_active_widgets` and
returns the first match.

## Timeframes

| Enum | Label | Angel interval | Bar seconds |
|---|---|---|---|
| `M1`  | 1m  | ONE_MINUTE      | 60    |
| `M3`  | 3m  | THREE_MINUTE    | 180   |
| `M5`  | 5m  | FIVE_MINUTE     | 300   |
| `M15` | 15m | FIFTEEN_MINUTE  | 900   |
| `H1`  | 1h  | ONE_HOUR        | 3600  |
| `D1`  | 1D  | ONE_DAY         | 86400 |

## Layout

```
ChartWidget (QDockWidget)
└── content (QWidget)
    ├── toolbar (34px fixed height)
    │   ├── symbol button (opens SearchDialog)
    │   ├── timeframe buttons [1m 3m 5m 15m 1h 1D]
    │   └── status label (Loading… / Live / Market Closed)
    └── ChartView (QWidget)
        └── GraphicsLayoutWidget
            ├── price_plot (70% height) ← OHLCItem + crosshair
            └── volume_plot (30% height, max 120px) ← VolumeItem
```

## Known Limitations / TODOs

- Historical data is limited to the last 500 bars (Angel API default pagination).
- `get_ltp()` workaround: chart subscribes in QUOTE mode for volume, but volume
  from feed is cumulative — the data manager adds `tick.volume` per tick which
  may double-count in QUOTE mode. Switch to SNAP_QUOTE for more accurate volumes.
- No indicators (MA, RSI, VWAP) — planned for Phase 7.
- No zoom-to-fit button — planned quality-of-life improvement.
