# CLAUDE.md

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                     # run Dash app on localhost:8050
```

## Structure

- `app.py` -- Dash app entry point (layout + callbacks + whale card builder)
- `analytics.py` -- Cached game-level checkpoint analytics, sport-specific quantile bands, and per-game regime summaries
- `charts.py` -- Plotly figure builders (pregame 3-row figure; in-game 4-row figure with whale markers and aggressor cumulative flow; sensitivity charts)
- `sensitivity.py` -- Per-event scoring sensitivity computation and cache loader
- `loaders.py` -- Data loading and parsing
- `whales.py` -- Whale wallet identification, classification, filtering, and maker/taker trade-size stats
- `chart_settings.json` -- Configurable thresholds (volume spikes, whale detection, whale marker minimum size, sensitivity windows/bins)
- `cache/` -- Local computed artifacts such as per-game sensitivity JSON cache
- `DATA_SPEC.md` -- Upstream data format reference (from poly-data-downloader)
- `data/` -- Trade data directories (YYYY-MM-DD format, not checked in)

## Key Patterns

- Data comes from `poly-data-downloader` -- see `DATA_SPEC.md` for schema
- `outcomes[0]` / `token_ids[0]` = away team, `[1]` = home team
- UI is multi-sport (`nba`, `nhl`, `mlb`), but event quality still varies by sport; missing events should degrade gracefully
- NBA events use `time_actual` (UTC wall-clock), directly comparable to trade timestamps
- Tricode-to-team mapping is built dynamically from score changes in events (no static lookup)
- `gamma_start_time` is scheduled start (can be ~12 min off); first event `time_actual` is actual tip-off
- Use `add_shape` + `add_annotation` for vertical lines on Plotly subplots (not `add_vline`)
- Whale classification: Market Maker (high maker %, 20+ trades), Directional (high taker %), Hybrid (mixed). Side attribution is taker-only; maker flow is passive.
- `Top Aggressors (Takers)` excludes wallets classified as `Market Maker` even if they have trivial taker flow.
- In-game price markers and the extra cumulative whale panel are driven by the ranked top-10 taker whales.
- `chart_settings.json` controls whale detection thresholds (`whale_min_volume_pct`, `whale_max_count`, `whale_maker_threshold_pct`) plus `whale_marker_min_trade_pct` for suppressing small plotted whale trades.
- Regime analytics should be built from favorite-side probabilities, not both token prices independently.
- Quantile bands are computed separately by sport and by active `price_quality` slice.
- The analytics `open` anchor is a "meaningful open": first pregame trade prices after cumulative pregame volume reaches `pregame_min_cum_vol`, not raw `selected_early_price`.
