# Option Chain Widget

## Overview

`widgets/option_chain/option_chain_widget.py` — a live option chain viewer for any index or stock.
Displays CE strikes on the left, the strike price in the centre, and PE strikes on the right.
All strike rows are fed by MarketFeed `SNAP_QUOTE` subscriptions. The underlying spot price
is fetched once via the broker REST API and then kept live via an `LTP` mode subscription.

---

## File Structure

```
widgets/option_chain/
├── __init__.py                  — self-registers with WidgetRegistry
├── option_chain_widget.py       — main QDockWidget, toolbar, LTP bar, table
├── option_chain_model.py        — QAbstractTableModel + OptionChainHeaderView
├── option_chain_row.py          — OptionChainRow dataclass (one strike)
├── option_chain_builder.py      — builds rows from InstrumentMaster
├── iv_calculator.py             — Black-Scholes IV (Newton-Raphson) and Delta
└── column_selector_dialog.py    — column visibility dialog
```

---

## Chain Building from InstrumentMaster

Options are stored in the NFO exchange segment in the instrument master.
Key fields:

| Field          | Example             | Notes                                      |
|----------------|---------------------|--------------------------------------------|
| `name`         | `"NIFTY"`           | Underlying name — filter key               |
| `expiry`       | `"24DEC2024"`       | Format `%d%b%Y` (uppercase month)          |
| `strike`       | `"2450000.000000"`  | In paise — divide by 100 for rupee strike  |
| `instrumenttype` | `"OPTIDX"`        | `"OPTIDX"` or `"OPTSTK"`                  |
| `exch_seg`     | `"NFO"`             | Exchange                                   |
| `token`        | `"35003"`           | Subscription token                         |
| `symbol`       | `"NIFTY24DEC2424500CE"` | Ends with `CE` or `PE`               |

`OptionChainBuilder.build_chain()` directly iterates `InstrumentMaster._index` (the raw
`list[tuple[str, str, dict]]`) for performance — no result-count limit applies.

Expiry strings are parsed with `datetime.strptime(s, "%d%b%Y")` and sorted ascending
(nearest expiry first) before populating the combo box.

---

## IV Calculation

IV is computed using Black-Scholes with Newton-Raphson iteration (`iv_calculator.py`):

1. **Model**: standard European Black-Scholes for CE and PE.
2. **Initial guess**: σ = 0.30 (30%).
3. **Iteration**: up to 100 steps; stops when `|price - market_price| < 1e-6` or `vega < 1e-10`.
4. **Result**: returned as a percentage (e.g., 18.5 for 18.5%). Returns 0.0 on failure or invalid inputs.
5. **Risk-free rate**: 6.5% (India approximately).

`scipy.stats.norm.cdf` is used for the normal CDF. `scipy` must be installed (`uv add scipy`).

Delta is computed from the same d1 value after Newton-Raphson converges.
CE delta ∈ (0, 1), PE delta ∈ (-1, 0).

**Limitation**: OI and OI Change fields are not currently parsed by `MarketFeed._parse_tick()`
because the `Tick` model does not include them. They display as `—` until the Tick model is extended.

---

## Token Subscription Strategy

- CE and PE tokens for each strike are subscribed in **`SNAP_QUOTE`** mode — provides LTP, volume, OHLC.
- The underlying index/stock is subscribed in **`LTP`** mode (saves tokens).
- **Subscription limit guard**: if total CE+PE tokens exceed 950, only strikes within ±50 of ATM
  are subscribed. A warning is logged. This avoids hitting the Angel 1000-token WebSocket limit.

### Common index tokens (hardcoded)

| Index       | Token | Exchange |
|-------------|-------|----------|
| NIFTY       | 26000 | NSE      |
| BANKNIFTY   | 26009 | NSE      |
| FINNIFTY    | 26037 | NSE      |
| MIDCPNIFTY  | 26074 | NSE      |
| SENSEX      | 1     | BSE      |

Stock options: the widget searches InstrumentMaster for `{NAME}-EQ` on NSE.

---

## ATM Computation

ATM strike = `min(rows, key=lambda r: abs(r.strike - underlying_ltp)).strike`

The ATM row is highlighted with background `#1f2937`. ITM CE (strike < spot) gets a subtle green
tint (`#0d1a0d`); ITM PE (strike > spot) gets a subtle red tint (`#1a0d0d`). ATM recomputes on
every underlying tick.

---

## Two-Row Header (`OptionChainHeaderView`)

`OptionChainHeaderView` subclasses `QHeaderView` with `sizeHint()` returning 2× normal height.
`paintSection()` splits the section rect into two halves:

- **Top half**: group background (CALLS green `#1a2a1a`, PUTS red `#2a1a1a`, CENTER `#161b22`).
  Group label text ("CALLS" / "PUTS") is drawn **only on the first column of the group**,
  in a rect spanning all group columns' combined width — giving a correct spanning visual.
- **Bottom half**: individual column label in `#8b949e`.

The two halves are separated by a `#30363d` border line.

---

## Column Visibility

`ALL_COLUMNS` in `option_chain_model.py` is the single source of truth for column order,
labels, sides, visibility, and default widths.
`ColumnSelectorDialog` reads and writes `ColumnDef.visible` in-place.
After `Apply`, `OptionChainWidget` calls `beginResetModel()/endResetModel()` to force the
header and table to repaint with the new column set.

Columns `ce_ltp`, `strike`, `pe_ltp` are always visible (`_ALWAYS_VISIBLE` set).

---

## State Persistence

```python
{
    "underlying":      "NIFTY",
    "expiry":          "24DEC2024",
    "visible_columns": ["ce_oi", "ce_oi_chg", "ce_iv", "ce_ltp", "strike", "pe_ltp", "pe_iv", "pe_oi_chg", "pe_oi"]
}
```

On `restore_state()` the widget reloads the chain via the background worker (same path as a fresh load).

---

## Known Limitations / TODOs

- OI and OI Change are always `0` / `"—"` because `MarketFeed._parse_tick()` does not
  currently extract `open_interest` / `open_interest_change` from the SNAP_QUOTE payload.
  Fix: extend `Tick` model and `_parse_tick()` with those fields.
- Bracket order support — not applicable here but noted for completeness.
- BSE option chain (BFO exchange) is not implemented yet.
- Stock option discovery relies on instrument name search; stocks with ambiguous names may
  not resolve correctly.
