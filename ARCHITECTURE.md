# Architecture

## Overview

Single-page Dash application that loads Polymarket trade data from disk and renders interactive Plotly charts plus per-game regime analytics. Current UI supports NBA, NHL, and MLB in a single-game view, with analytics computed from cross-game checkpoint data within the active sport and price-quality slice.

## Components

### `loaders.py` -- Data Loading

- Scans `data/` for date directories, loads `manifest.json`, filters to collected NBA games
- `load_game()` loads gzip-compressed trades/events files into a pandas DataFrame, parses events, builds tricode-to-team mapping by tracking score changes, parses gamma timestamps
- `_read_json()` helper auto-detects `.gz` suffix for transparent gzip/plain JSON reading
- Returns a dict with manifest, trades DataFrame, events list, tricode map, and parsed timestamps

### `analytics.py` -- Game-Level Regime Analytics

- Scans all collected trade files and extracts only checkpoint headers needed for cross-game analysis
- Computes per-game favorite-side snapshots for:
  - market open (short post-threshold pregame VWAP/median window after cumulative pregame volume reaches `pregame_min_cum_vol`)
  - tip-off (`last_pregame_trade_price`)
- Assigns interpretable favorite-strength bands:
  - `Toss-Up`
  - `Lean Favorite`
  - `Lower Moderate`
  - `Upper Moderate`
  - `Lower Strong`
  - `Upper Strong`
- Computes sport-specific quantile cutoffs and quantile bands (`Q1`, `Q2`, `Q3`)
- Supports `price_quality` filtered comparison populations (`all`, `exact`, `inferred`)
- NBA analysis can drop ultra-tight opens using `analysis_min_open_favorite_price`, and reports how many games were excluded by that rule
- Exposes cached analytics records used by the UI controls and the game analytics card
- Equal favorite-side prices are represented as `Tie` rather than defaulting to token order

### `charts.py` -- Chart Building

- `build_charts()` builds two subplot figures:
  - **Pre-game:** 3-row shared-x-axis figure
  - **In-game:** 4-row shared-x-axis figure when top taker whales are present
- Shared rows:
  - **Row 1 (55%):** Price lines for both tokens, vertical reference lines (scheduled start, tip-off, market close), scoring event markers, and top-10 taker whale trade markers
  - **Row 2 (25%):** Stacked BUY/SELL volume bars (1-min or 5-min buckets), volume spike markers, and team-specific taker whale overlays such as `{Team} Whale Buy` / `{Team} Whale Sell`
  - **Row 3 (20%):** Cumulative volume line with rangeslider
- In-game only:
  - **Row 4:** Top aggressor cumulative-dollar panel, split by ranked whale, team, and taker direction
- Uses `Scattergl` (WebGL) for price lines to handle 10K+ trade datasets
- Event markers placed at nearest trade price (within 60s) or last known price
- Whale trade markers on Row 1 are filtered by `whale_marker_min_trade_pct` to suppress tiny fills
- Whale volume overlays on Row 2 are directional and taker-only; maker flow is intentionally excluded because side is not inferable

### `sensitivity.py` -- Event Sensitivity

- Computes per-scoring-event price sensitivity using the away token only
- Measures VWAP before and after each scoring event using the last `sensitivity_price_window_trades` fills before the event and the first `sensitivity_price_window_trades` fills after it
- Derives `pre_lead`, `post_lead`, `lead_bin`, and `time_bin` for each scoring play
- Caches computed rows to `cache/{date}/{match_id}_sensitivity.json` so repeated dashboard views do not recompute the same game
- Supplies the row-level data used by the sensitivity timeline scatter and the quarter/time-bucket surface summaries

### `whales.py` -- Whale Analysis

- `analyze_whales()` identifies high-volume wallets exceeding a configurable % of total market volume
- Classification based on maker/taker ratio: **Market Maker** (high maker %, 20+ trades), **Directional** (high taker %), **Hybrid** (mixed)
- Side attribution uses taker trades only (BUY/SELL/Mixed)
- Per-wallet stats include maker and taker trade-size summaries: count, min, max, mean, median
- `get_whale_trades()` filters a trades DataFrame to only trades involving whale addresses
- Settings: `whale_min_volume_pct` (threshold), `whale_max_count` (cap), `whale_maker_threshold_pct` (classification boundary), `whale_marker_min_trade_pct` (minimum plotted whale trade size as % of game volume)

### `app.py` -- Dash Application

- Layout: dark theme, sport/date/game/price-quality controls, info cards (game metadata, pre-game summary, game analytics, chart settings), whale tracker card, sensitivity charts, and the pre-game/in-game figures
- Whale tracker card renders separate full-width aggressor and maker sections rather than a shared two-column layout
- Three callbacks:
  1. Populate sport dropdown from cached analytics records
  2. Populate date and game dropdowns from the active sport / price-quality slice
  3. Load the selected game, run whale analysis, derive the top-10 non-maker taker whales, compute the sensitivity cache, build charts, and populate metadata / pre-game / analytics / whale cards

## Data Flow

```
data/YYYY-MM-DD/manifest.json
        |
        v
  analytics.py scan ------------------> cached game analytics table
        |                                         |
        v                                         v
 Sport/date/quality controls -> game dropdown   load_game()
                                                  |
                                                  v
                                  trades_df + events + manifest + game_row
                                                  |
                             +--------------------+--------------------+
                             |                                         |
                             v                                         v
                   analyze_whales() -> whale_data            build_analysis_summary()
                             |                                         |
                             v                                         v
               whale_addresses + top_taker_whales         _build_analysis_card()
                             |
                             v
 load_or_compute_sensitivity() -> sensitivity rows
                             |
                             v
 build_charts(...) + sensitivity figures -> Figures
           _build_pregame_card() -> Card
             _build_whale_card() -> Card
```

## Key Design Decisions

- **Tip-off anchor:** First event's `time_actual` (median 24s into Q1) rather than `gamma_start_time` (scheduled, ~12 min early on median)
- **Tricode mapping:** Dynamic -- tracks which tricode increases away vs home score across events. No static lookup table needed.
- **Vertical lines:** Uses `add_shape` + `add_annotation` instead of `add_vline` (Plotly convenience method fails on datetime subplot axes)
- See `plans/NBA_Game_Visualizer_Plan.md` for full design rationale
