# Trading Terminal

A Python desktop trading terminal built with PySide6 and Angel SmartAPI.

## Prerequisites

- Python 3.11+
- An Angel One account with SmartAPI access and TOTP enabled
- `uv` installed:
  ```bash
  pip install uv
  ```

## Installation

```bash
git clone https://github.com/yashginoya/DemonEdge
cd trading-terminal
uv sync
```

## Configuration

```bash
cp config/settings.example.yaml config/settings.yaml
```

Fill in `api_key`, `client_id`, `password`, and `totp_secret` from your [Angel SmartAPI portal](https://smartapi.angelbroking.com).

## Run

```bash
uv run python main.py
```
