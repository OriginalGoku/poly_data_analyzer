# Poly Data Analyzer

Dash+Plotly visualizer for Polymarket NBA game trade data. Renders price movement, trading volume, cumulative volume, and game event overlays for individual NBA games.

## Features

- **Price chart** -- Away and home token price lines (summing to ~1.0), with vertical markers for scheduled start, actual tip-off, and market close
- **Scoring event overlays** -- Made baskets plotted on the price line at the nearest trade price, with score/type/description on hover
- **Volume bars** -- Stacked BUY (green) / SELL (red) volume per time bucket (1-min or 5-min based on trading span)
- **Cumulative volume** -- Running total of USDC traded over time
- **Game metadata cards** -- Trade count, total volume, price quality, data source, pre-game summary with opening price, drift, and pre-game volume
- **Date/game dropdowns** -- Browse by date, select any collected NBA game

## Setup

```bash
pip install -r requirements.txt
```

Requirements: `dash`, `plotly`, `pandas`

## Usage

```bash
python app.py
```

Open `http://localhost:8050` in a browser. Select a date and game from the dropdowns.

## Data

Trade data is expected in `data/YYYY-MM-DD/` directories produced by `poly-data-downloader`. See `DATA_SPEC.md` for the full schema.

Each date directory contains:
- `manifest.json` -- index of all games for that date
- `{match_id}_trades.json` -- trade history per game
- `{match_id}_events.json` -- play-by-play events per game (NBA: made baskets only)

## Project Structure

```
app.py              # Dash app layout, dropdowns, callbacks
charts.py           # Plotly chart builders (3-row subplot: price, volume, cumulative)
loaders.py          # Data loading (dates, games, trades, events, tricode mapping)
requirements.txt    # Python dependencies
DATA_SPEC.md        # Upstream data format specification
data/               # Trade data directories (not checked in)
plans/              # Implementation plans
wiki/               # Decisions log
```
