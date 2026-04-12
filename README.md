# Poly Data Analyzer

Dash+Plotly visualizer for Polymarket sports market trade data. Renders price movement, trading volume, cumulative flow, whale activity, per-game regime analytics, and price sensitivity to scoring events for NBA, NHL, and MLB markets.

## Features

- **Price chart** -- Away and home token price lines (summing to ~1.0), with vertical markers for scheduled start, actual tip-off, and market close
- **Scoring event overlays** -- Made baskets plotted on the price line at the nearest trade price, with score/type/description on hover
- **Volume bars** -- Stacked BUY (green) / SELL (red) volume per time bucket (1-min or 5-min based on trading span), plus team-specific taker whale overlays like `Lakers Whale Buy`
- **Cumulative volume** -- Running total of USDC traded over time
- **Price sensitivity to scoring** -- Per-event VWAP delta around scoring plays, plus a timeline scatter and binned surface showing mean sensitivity by game phase and lead context
- **Game metadata cards** -- Trade count, total volume, price quality, data source, pre-game summary with opening price, drift, and pre-game volume
- **Game analytics card** -- Shows market-open and tip-off favorite strength for the selected game, with refined interpretable bands (`Toss-Up`, `Lean Favorite`, `Lower Moderate`, `Upper Moderate`, `Lower Strong`, `Upper Strong`) and sport-specific quantile bands (`Q1`, `Q2`, `Q3`). The market-open anchor now uses a short post-threshold pregame VWAP/median window after cumulative volume reaches the configured `Pre-Game Min Cum Vol` threshold.
- **Sport and price-quality filters** -- Slice the app by `NBA`, `NHL`, or `MLB`, and optionally restrict the analysis population to `all`, `exact`, or `inferred` checkpoint quality
- **Whale tracker** -- Identifies high-volume wallets, classifies them (Market Maker / Directional / Hybrid), and displays separate full-width `Top Aggressors (Takers)` and `Top Liquidity (Makers)` sections with rank, bias, position breakdown, and trade-size stats
- **Top-10 whale trade markers** -- In-game price chart highlights large trades from the top taker whales, showing rank, team, direction, amount, and price on hover
- **Top aggressor cumulative panel** -- In-game chart includes a second cumulative-dollar row that tracks each ranked taker whale's buy/sell flow by team over time
- **Date/game dropdowns** -- Browse by sport and date, then select any collected game in the filtered slice

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
- `{match_id}_trades.json.gz` -- trade history per game (gzip-compressed)
- `{match_id}_events.json.gz` -- play-by-play events per game (gzip-compressed; NBA: made baskets only)

## Project Structure

```
app.py              # Dash app layout, dropdowns, callbacks, whale card builder
analytics.py        # Cached game-level checkpoint analytics and regime band assignment
charts.py           # Plotly figure builders (pregame: 3 rows, in-game: 4 rows with top aggressor cumulative; sensitivity charts)
loaders.py          # Data loading (dates, games, trades, events, tricode mapping)
sensitivity.py      # Per-event scoring sensitivity computation and cache loader
whales.py           # Whale wallet identification, classification, side attribution, and trade-size stats
chart_settings.json # Configurable thresholds (volume spikes, whale detection, whale marker minimum size, sensitivity windows/bins)
cache/              # Local computed artifacts, including per-game sensitivity JSON cache
requirements.txt    # Python dependencies
DATA_SPEC.md        # Upstream data format specification
data/               # Trade data directories (not checked in)
plans/              # Implementation plans
wiki/               # Decisions log
```
