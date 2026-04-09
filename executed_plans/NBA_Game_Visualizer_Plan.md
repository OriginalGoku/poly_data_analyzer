# NBA Game Visualizer

> Dash+Plotly single-game viewer for NBA Polymarket trade data with game event overlays and key market timestamps.

---

## Problem Statement

The repo is a pure data store — 719 date directories, ~2,718 collected NBA games, zero analysis or visualization code. Before running quantitative volatility analysis, we need to visually inspect the data: price movement over time, trading volume patterns, and game events overlaid on the price chart. This tool enables exploratory understanding of the data.

## Design Decisions

### D1: Dash+Plotly over Streamlit

**Decision:** Use Dash with Plotly for the UI framework.

**Rationale:** More control over chart interactivity, better synced zoom/pan across subplots, richer callback system. User preferred a more solid visual representation than Streamlit.

**Trade-off:** Streamlit would be faster to build but less flexible for financial-style charting.

### D2: NBA-only, single game view

**Decision:** Scope to NBA games only, one game at a time.

**Rationale:** NBA has the best data for this use case — `time_actual` wall-clock timestamps on events (NHL lacks this, MLB only has scoring plays). Single game view keeps scope tight. Multi-game comparison and NHL/MLB support deferred.

### D3: No bid/ask spread visualization

**Decision:** Skip spread visualization for now.

**Rationale:** Trade data contains executed fills only (no order book snapshots). While BUY/SELL trades approximate ask/bid hits, the user chose to focus on the data as-is rather than approximate spreads. Can revisit later.

### D4: First event `time_actual` as tip-off anchor

**Decision:** Use the first NBA event's `time_actual` (UTC wall-clock) as the actual game start marker, with `gamma_start_time` as a secondary "scheduled start" marker.

**Rationale:** First made basket happens median 24s into Q1 (93% within 1 min). `gamma_start_time` is the scheduled start and runs ~12 min early on median vs actual tip-off. Showing both lets the user see the gap.

### D5: Combined subplots with shared x-axis

**Decision:** Use `plotly.subplots.make_subplots` with shared x-axis for price, volume, and cumulative charts as one figure.

**Rationale:** Native synced zoom/pan. Three separate figures would require manual x-axis synchronization via callbacks — more code, worse UX.

### D6: Tricode-to-team mapping via score tracking

**Decision:** Map `team_tricode` in events to away/home by iterating events and tracking which tricode increases `away_score` vs `home_score`.

**Rationale:** No static tricode-to-team lookup exists in the data. This dynamic approach handles all team names correctly. Verified: events `team1` = away = `outcomes[0]`, `team2` = home = `outcomes[1]`.

## Codebase Context

- **No existing code** — entirely greenfield. No Python files, no `requirements.txt`, no package config.
- **Data lives in** `data/YYYY-MM-DD/` with `manifest.json` + per-game `_trades.json` and `_events.json`
- **Key data mappings verified**:
  - `outcomes[0]` = away team = `token_ids[0]`, `outcomes[1]` = home team = `token_ids[1]`
  - Events `team1` = away, `team2` = home (matches manifest `away_team`/`home_team`)
  - `time_actual` on NBA events is UTC wall-clock, directly comparable to trade `timestamp` (Unix seconds)
- **Trade files are 1.5-5MB each** — loading one game at a time is fine, no caching needed

## Implementation Plan

### Step 1: Project setup and data loaders
Files: `loaders.py` (new), `requirements.txt` (new)
Depends on: none

- `requirements.txt` — `dash`, `plotly`, `pandas`
- `loaders.py` — three functions:
  - `get_available_dates(data_dir) -> list[str]` — scan `data/` for date directories
  - `get_nba_games(data_dir, date) -> list[dict]` — load `manifest.json`, filter to `sport=="nba"` and `status=="collected"`, return manifest entries
  - `load_game(data_dir, date, match_id) -> dict` — load trades file into pandas DataFrame (columns: `timestamp`, `datetime`, `price`, `size`, `side`, `asset`, `team`). Load events file if exists, parse `time_actual` to datetime. Build tricode-to-team map from score tracking. Parse `gamma_start_time`/`gamma_closed_time` to datetime (empty string -> None). Return `{"manifest": entry, "trades_df": df, "trades_meta": header_fields, "events": events_or_none}`

### Step 2: Plotly chart builders
Files: `charts.py` (new)
Depends on: Step 1

- `build_price_chart(...)` — combined subplots figure with three rows, shared x-axis, row heights `[0.55, 0.25, 0.20]`:
  - **Row 1 (Price):** Two scatter lines (away + home token price over time, colored by team). Vertical markers: `gamma_start_time` (dashed gray, "Scheduled Start"), first event `time_actual` (solid green, "Tip-Off"), `gamma_closed_time` (dashed red, "Market Close"). Event markers: scatter points at each scoring event's `time_actual` on the corresponding team's price line (nearest trade price as y-coordinate, fallback to last known price if no trade within 60s). Hover: score + event type + description. Use `scattergl` for performance (10K+ trades).
  - **Row 2 (Volume):** Stacked bar chart — BUY (green) + SELL (red) per time bucket (1-min if <6h trading span, 5-min otherwise).
  - **Row 3 (Cumulative volume):** Cumulative sum of `size` over time, vertical line at tip-off.
  - X-axis rangeslider on bottom row for zoom.

### Step 3: Dash app layout and callbacks
Files: `app.py` (new)
Depends on: Step 1, Step 2

**Layout:**
- Top bar: date dropdown + game dropdown (chained)
- Game metadata card: teams, final score, trade count, total volume, price quality, data source, truncated flag
- Pre-game summary card: opening price (from `price_checkpoints` with source label), last pre-tipoff price (recomputed from trades using actual tip-off anchor), drift, pre-game trade count, pre-game volume
- Main chart area: combined subplots figure

**Callbacks:**
1. Date change -> populate game dropdown with `"Away @ Home"` labels, `match_id` values
2. Game change -> load data, build charts, populate both cards

**Defaults:** most recent date with NBA games, first game in list.

## Execution Preview

```
Wave 0:  Step 1 — Project setup and data loaders
Wave 1:  Step 2 — Plotly chart builders
Wave 2:  Step 3 — Dash app layout and callbacks
```

Critical path: Step 1 -> Step 2 -> Step 3 (3 waves, sequential)

## Risk Flags

- **Tricode mapping edge case**: If a game has 0 events or only one team scores, tricode map is incomplete. Fallback: skip event markers, still show price/volume.
- **Large trade files**: 10K+ point scatter can be sluggish. Mitigation: `scattergl` (WebGL renderer).
- **Historical NBA games**: `nba-dailies-*`, `nba-play-in-*` have empty `gamma_start_time`, low trade counts. Viewer still loads them — missing vertical markers, sparse charts. No special handling beyond null checks.
- **Missing events files**: ~77 NBA games lack events (CDN 403). Charts render without event markers.

## Verification

1. `pip install -r requirements.txt`
2. `python app.py`
3. Navigate to `http://localhost:8050`
4. Select `2025-11-14` -> `Heat @ Knicks`
5. Verify: two price lines (summing to ~1.0), volume bars, cumulative volume, scheduled start / tip-off / market close markers, scoring event dots with hover showing score
