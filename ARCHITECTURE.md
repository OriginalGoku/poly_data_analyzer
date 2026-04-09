# Architecture

## Overview

Single-page Dash application that loads Polymarket NBA trade data from disk and renders interactive Plotly charts. NBA-only scope (best event data quality). Single game view.

## Components

### `loaders.py` -- Data Loading

- Scans `data/` for date directories, loads `manifest.json`, filters to collected NBA games
- `load_game()` loads trades into a pandas DataFrame, parses events, builds tricode-to-team mapping by tracking score changes, parses gamma timestamps
- Returns a dict with manifest, trades DataFrame, events list, tricode map, and parsed timestamps

### `charts.py` -- Chart Building

- `build_price_chart()` builds a 3-row shared-x-axis subplot figure:
  - **Row 1 (55%):** Price lines for both tokens, vertical reference lines (scheduled start, tip-off, market close), scoring event markers
  - **Row 2 (25%):** Stacked BUY/SELL volume bars (1-min or 5-min buckets)
  - **Row 3 (20%):** Cumulative volume line with rangeslider
- Uses `Scattergl` (WebGL) for price lines to handle 10K+ trade datasets
- Event markers placed at nearest trade price (within 60s) or last known price

### `app.py` -- Dash Application

- Layout: dark theme, date/game dropdowns, two info cards, main chart
- Three callbacks:
  1. Populate date dropdown (default: most recent date with NBA games)
  2. Chain game dropdown from selected date (label: "Away @ Home")
  3. Load data, build chart, populate game metadata and pre-game summary cards

## Data Flow

```
data/YYYY-MM-DD/manifest.json
        |
        v
  get_available_dates() -> get_nba_games() -> load_game()
        |                                         |
        v                                         v
  Date dropdown -> Game dropdown          trades_df + events + manifest
                                                  |
                                                  v
                                        build_price_chart() -> Figure
                                        _build_pregame_card() -> Card
```

## Key Design Decisions

- **Tip-off anchor:** First event's `time_actual` (median 24s into Q1) rather than `gamma_start_time` (scheduled, ~12 min early on median)
- **Tricode mapping:** Dynamic -- tracks which tricode increases away vs home score across events. No static lookup table needed.
- **Vertical lines:** Uses `add_shape` + `add_annotation` instead of `add_vline` (Plotly convenience method fails on datetime subplot axes)
- See `plans/NBA_Game_Visualizer_Plan.md` for full design rationale
