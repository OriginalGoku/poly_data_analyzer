# Whale Tracker

> Add whale wallet identification, classification (Market Maker / Directional / Hybrid), and visualization to the NBA game viewer.

---

## Problem Statement

Trade data now includes `maker` and `taker` wallet addresses on each trade. Volume is heavily skewed — top 5 wallets account for ~65% of volume per game, with the #1 wallet often doing 50%+ (~$1.3M in a single game). Users need to identify these large-scale participants, understand their role (liquidity provider vs directional bettor), and see when whale activity occurs during a game.

## Design Decisions

### D1: Side attribution is taker-only

**Decision:** Buy/sell directional bias is computed only from taker trades. Maker trades contribute volume only, no side attribution.

**Rationale:** `side` is the fill direction relative to the token (per DATA_SPEC.md). The taker is the aggressor who initiated the fill (directional intent). The maker posted a passive limit order — attributing trade direction to them would invert their actual position half the time and systematically misclassify wallets.

**Trade-off:** Makers lose directional detail, but their volume and trade count still inform classification. Attributing side to both participants would produce incorrect classifications.

### D2: Scatter line overlay, not bar overlay

**Decision:** Whale volume overlay uses `go.Scatter` with `fill="tozeroy"` and low opacity, not `go.Bar`.

**Rationale:** `barmode="stack"` is figure-level in Plotly. Adding whale `go.Bar` traces would either stack on top (inflating y-axis) or require switching `barmode` to `"overlay"` (breaking existing stacked bars). A Scatter fill area communicates magnitude over time without conflicting.

**Trade-off:** Bars would be more visually consistent with the volume row, but they break the existing chart. The Scatter approach is proven safe and still shows magnitude clearly.

### D3: Two leaderboards instead of one blended list

**Decision:** The whale card shows two separate ranked lists: "Top Aggressors (Takers)" and "Top Liquidity (Makers)".

**Rationale:** A single blended list ranked by total volume would bury large passive market makers beneath aggressive takers. Two lists let users see both sides of the market. A wallet can appear in both lists if it has significant volume in both roles.

**Trade-off:** More UI space used, but both maker and taker whales are equally visible.

### D4: Volume denominator is single-counted trade volume

**Decision:** `pct_of_total = wallet_total_volume / trades_df["size"].sum() * 100` where each trade is counted once.

**Rationale:** Each trade has one maker and one taker. Wallet `total_volume` = `maker_volume + taker_volume`. Using single-counted trade volume as denominator means a wallet's % can theoretically exceed 50% if it's on many trades, but the number is accurate and intuitive. The alternative (2x participant-volume denominator) would cap % at ~50% but is conceptually muddier.

### D5: New `whales.py` module

**Decision:** Whale analysis lives in a dedicated `whales.py` module, not in loaders.py or charts.py.

**Rationale:** The analysis is a distinct analytical concern. loaders.py loads raw data, charts.py renders figures. A separate module maintains single-responsibility and follows the existing architecture pattern.

## Codebase Context

- **Existing patterns to reuse:**
  - `_info_row(label, value)` in `app.py:24` for card formatting
  - `_mark_volume_spikes()` in `charts.py:351` — same bucketing pattern for whale overlay
  - `chart_settings.json` settings flow: loaded in `app.py`, passed via `settings=` param
  - `legend="legend2"` assignment for Row 2 traces
- **Prior lesson (HIGH salience):** Plotly `add_vline` fails on datetime subplot axes — use `add_shape` + `add_annotation` directly
- **trades_df columns:** `side, asset, price, size, timestamp, transactionHash, fill_id, maker, taker, datetime, team`

## Implementation Plan

### Step 1: Whale analysis module
Files: whales.py (new), tests/test_whales.py (new)
Depends on: none

- `whales.py` — new module with two public functions:
  - `analyze_whales(trades_df: pd.DataFrame, settings: dict) -> dict` — per-wallet volume stats, classification, filtering
  - `get_whale_trades(trades_df: pd.DataFrame, whale_addresses: set[str]) -> pd.DataFrame` — filter trades to whale participants
- Per wallet (union of `maker` + `taker` columns):
  - `maker_volume`, `taker_volume`, `total_volume`, `trade_count`
  - From taker trades only: `buy_volume`, `sell_volume`, `teams_traded`
  - `pct_of_total = total_volume / trades_df["size"].sum() * 100`
- Filter: `pct_of_total >= whale_min_volume_pct` (default 2%), cap at `whale_max_count` (default 10)
- Classification:
  - Market Maker: `maker_pct >= whale_maker_threshold_pct` AND `trade_count >= 20`
  - Directional: `taker_pct >= whale_maker_threshold_pct`
  - Hybrid: else
- Primary side (taker trades only): BUY if >65% taker vol, SELL if >65%, else Mixed
- `display_addr`: `f"0x{addr[2:6]}...{addr[-4:]}"`
- Returns `{"whales": [...], "summary": {...}}`
- `tests/test_whales.py` — tests for classification, threshold filtering, max count cap, side attribution, empty DataFrame, `get_whale_trades`

### Step 2: Add whale settings
Files: chart_settings.json
Depends on: none

- Add 3 keys to `chart_settings.json`:
  - `whale_min_volume_pct`: 2.0
  - `whale_max_count`: 10
  - `whale_maker_threshold_pct`: 60
- All consumed via `settings.get()` with defaults — backward-compatible

### Step 3: Chart whale volume overlay
Files: charts.py
Depends on: Step 1

- `build_charts()` — add `whale_addresses: set[str] | None = None` param, pass to `_build_subplot_figure()`
- `_build_subplot_figure()` — add `whale_addresses` param, call `_add_whale_volume_line()` after spike markers if non-empty
- New `_add_whale_volume_line(fig, trades_df, whale_addresses)`:
  - Same bucketing as `_add_volume_bars` (reuse freq calculation)
  - Filter trades where `maker in whale_addresses OR taker in whale_addresses`
  - `go.Scatter` line with `fill="tozeroy"`, `opacity=0.15`, color `#FFD600`
  - Hover: whale volume + % of bucket total
  - `legend="legend2"`, named "Whale Vol"

### Step 4: Whale card and app integration
Files: app.py
Depends on: Step 1, Step 2, Step 3

- Import `analyze_whales` from `whales`
- In `update_game()`:
  - Call `whale_data = analyze_whales(trades_df, SETTINGS)` before `build_charts()`
  - Extract `whale_addresses`, pass to `build_charts()`
  - Add `Output("whale-card", "children")` (5th output)
- Add `html.Div(id="whale-card")` to layout below info cards
- New `_build_whale_card(whale_data)`:
  - Summary: "N whales = X% of volume"
  - Two sub-sections: Top Aggressors (by taker_volume), Top Liquidity (by maker_volume)
  - Per wallet: display_addr, volume, %, classification badge, primary side
  - Badge colors: Market Maker=#4CAF50, Directional=#FF5722, Hybrid=#FFC107
- Settings card: add 3 whale settings to display

## Execution Preview

```
Wave 0 (2 parallel):  Step 1 — Whale analysis module, Step 2 — Add whale settings
Wave 1 (1 sequential): Step 3 — Chart whale volume overlay
Wave 2 (1 sequential): Step 4 — Whale card and app integration
```

Critical path: Step 1 -> Step 3 -> Step 4 (3 waves)
Max parallelism: 2 agents

## Risk Flags

- **`barmode="stack"` conflict avoided** — whale overlay uses `go.Scatter`, not `go.Bar`
- **Side attribution** — buy/sell only from taker trades; verified against real data
- **`maker`/`taker` fields undocumented** — exist in data but not in `DATA_SPEC.md`; low risk (from on-chain event logs)
- **Volume denominator** — wallet % can exceed 50%; accurate but may surprise users

## Verification

1. `python -m pytest tests/ -v` — all existing + new tests pass
2. `python app.py` -> select 2026-04-09 game -> verify:
   - Whale card shows two leaderboards
   - Top taker `0x4bfb...982e` classified as Directional, primary_side=SELL
   - High-trade-count maker wallets classified as Market Maker
   - Settings card shows 3 new whale settings
3. Volume chart shows yellow whale volume fill on Row 2
4. Hover on whale overlay shows whale volume and % of bucket
