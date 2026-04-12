# Price Sensitivity to Scoring Events

> Compute per-event price reactions to scoring plays and visualize as a timeline scatter (Option A) and binned sensitivity surface (Option B), with per-game disk caching.

---

## Problem Statement

The app shows price and score progression as separate charts with no quantified relationship between them. Users want to understand how scoring at different points in the game affects market pricing — the price sensitivity to scoring events over time. This plan adds per-event Δprice computation (VWAP of N trades before/after each scoring event) and two new charts: a timeline scatter showing price impact per event, and a binned bar chart showing mean sensitivity by game phase × lead context. Per-event data is cached to disk so it's computed once per game.

## Design Decisions

### D1: Cache location — local `cache/` directory, not game data folder

**Decision:** Store cached sensitivity data in `cache/{date}/{match_id}_sensitivity.json` within this repo.

**Rationale:** The `data/` directory is a symlink to `poly-data-downloader/data`. Writing computed artifacts into upstream data folders couples the analyzer to the downloader's directory structure and risks polluting source data.

**Trade-off:** Considered writing alongside game data for co-location. Rejected due to symlink ownership and potential data loss if downloader re-syncs.

### D2: Price measurement — VWAP of N trades before/after

**Decision:** Compute VWAP (volume-weighted average price) of the last 5 trades before and first 5 trades after each scoring event. The window size (5) is configurable via `sensitivity_price_window_trades` in `chart_settings.json`.

**Rationale:** VWAP accounts for trade size, giving more weight to larger trades. Simple mean ignores that a single large trade is more informative than several small ones.

**Trade-off:** Simple mean is easier to explain. VWAP chosen because the codebase already uses VWAP for the open anchor price (`open_anchor_stat: "vwap"`), maintaining consistency. Fallback: if fewer than N trades exist, use however many are available (minimum 1).

### D3: Lead bins — 3 bins (Close / Moderate / Blowout)

**Decision:** Classify pre-event score lead into 3 bins with configurable thresholds:
- Close: 0–5 pts (`sensitivity_lead_bin_close`)
- Moderate: 6–12 pts (`sensitivity_lead_bin_moderate`)
- Blowout: 13+ pts

**Rationale:** ~80-100 scoring events per NBA game. 3 bins × 4 quarters = 12 cells, averaging 7-8 events per cell. More bins would leave too many cells empty in a single game. Thresholds are configurable for later tuning.

**Trade-off:** Considered 2 bins (Close/Not Close) — too coarse. 4+ bins — too sparse per game. 3 is the sweet spot for per-game prototype; can refine when cross-game aggregation is added.

### D4: Game phase — both quarter-based and time-based views

**Decision:** The sensitivity surface chart shows two subplots: one binned by quarter (Q1-Q4+OT), one by minutes-since-tipoff (6-min buckets).

**Rationale:** Quarter bins are natural for NBA (strategy shifts at quarter boundaries). Time bins are more granular and generalize better if cross-sport support is added later. Both are trivially derivable from the same cached per-event data.

### D5: Away token only for price measurement

**Decision:** Measure Δprice on the away team token (`outcomes[0]` / `token_ids[0]`) only.

**Rationale:** Prices of the two tokens sum to ~1.0. Measuring both is redundant — home Δprice is the negative of away Δprice. Using one token avoids sign-convention confusion.

## Codebase Context

- **Existing alignment infrastructure:** `_score_lead_series_for_times()` uses `pd.merge_asof(direction="backward")` to join trades with scores — same pattern reusable
- **Empty figure pattern:** `_empty_score_figure(message, height)` — reuse for NBA-only graceful degradation
- **Settings pattern:** Frozen `ChartSettings` dataclass in `settings.py`, loaded from `chart_settings.json` via `from_dict(**data)` unpacking
- **Callback pattern:** 8 outputs in `pages/main_dashboard_page.py` — two new `dcc.Graph` outputs needed (grows to 10)
- **Chart convention:** Use `add_shape` + `add_annotation` for vertical lines, NOT `add_vline` (HIGH salience decision from decisions-log)
- **Events:** NBA-only with `time_actual_dt`, `period`, `away_score`, `home_score`, `team_tricode`, `event_type`
- **Tipoff:** First event's `time_actual_dt`, not `gamma_start_time`

## Implementation Steps

### Step 1: Add sensitivity settings to ChartSettings
Files: settings.py, chart_settings.json
Depends on: none

**What changes:**
- `chart_settings.json` — add 3 new keys:
  ```json
  "sensitivity_price_window_trades": 5,
  "sensitivity_lead_bin_close": 5,
  "sensitivity_lead_bin_moderate": 12
  ```
- `settings.py` — add 3 new fields to `ChartSettings` dataclass with matching defaults, update `to_dict()` to include them

**Key details:**
- `sensitivity_price_window_trades` (int, default 5): number of trades before/after event for VWAP
- `sensitivity_lead_bin_close` (int, default 5): upper bound of "Close" lead bin (inclusive)
- `sensitivity_lead_bin_moderate` (int, default 12): upper bound of "Moderate" bin (inclusive); above = "Blowout"
- Frozen dataclass — `from_dict()` already uses `**data` unpacking, so new fields are picked up automatically

---

### Step 2: Create sensitivity computation module
Files: sensitivity.py (new)
Depends on: Step 1

**What changes:**
- New module `sensitivity.py` with two public functions:
  - `compute_event_sensitivity(trades_df, events, manifest, settings) -> pd.DataFrame | None`
  - `load_or_compute_sensitivity(cache_dir, date, match_id, trades_df, events, manifest, settings) -> pd.DataFrame | None`

**`compute_event_sensitivity` logic:**
1. Filter events to scoring events (non-null `time_actual_dt`, `away_score`, `home_score`)
2. Filter trades to in-game only (after tipoff = first event `time_actual_dt`)
3. Sort trades by datetime
4. For each scoring event:
   - Derive `points` from `event_type`: 2pt→2, 3pt→3, freethrow→1
   - Compute `pre_lead` = `abs(away_score - home_score)` from the **previous** event (or 0 for first event)
   - Compute `post_lead` = `abs(away_score - home_score)` after this event
   - Find last N trades before `time_actual_dt` on the away token → VWAP = `sum(price*size)/sum(size)`
   - Find first N trades after `time_actual_dt` on the away token → VWAP
   - `delta_price` = `vwap_after - vwap_before`
   - `seconds_since_tipoff` = `(event_time - tipoff_time).total_seconds()`
   - `lead_bin` = classify `pre_lead` using thresholds from settings
   - `time_bin` = `seconds_since_tipoff // 360` (6-min buckets)
   - `trades_before_count`, `trades_after_count` = actual trades found (may be < N)
5. Return DataFrame with columns: `event_time`, `team`, `points`, `period`, `seconds_since_tipoff`, `pre_lead`, `post_lead`, `lead_bin`, `time_bin`, `price_before`, `price_after`, `delta_price`, `trades_before_count`, `trades_after_count`
6. Return `None` if no events or no valid event-price pairs

**`load_or_compute_sensitivity` logic:**
1. Build cache path: `{cache_dir}/{date}/{match_id}_sensitivity.json`
2. If file exists → load and return as DataFrame
3. Else → call `compute_event_sensitivity()`, write result to JSON, return DataFrame
4. Create `cache/{date}/` directory if it doesn't exist

**Key details:**
- Away token trades only — use `manifest["token_ids"][0]` to filter
- VWAP with fallback: if fewer than N trades exist, use however many are available (minimum 1); if 0 trades → `None` for that price
- Cache format: JSON list of dicts, ISO timestamps serialized as strings
- `lead_bin` assignment: `pre_lead <= close_threshold` → "Close", `<= moderate_threshold` → "Moderate", else → "Blowout"
- Add `cache/` to `.gitignore`

---

### Step 3: Add sensitivity chart builders
Files: charts.py
Depends on: Step 2

**What changes:**
- Add two new public functions:

**`build_sensitivity_timeline(sensitivity_df, manifest, events, title) -> go.Figure`**
- Scatter plot: x = `event_time`, y = `delta_price`
- Markers colored by `team` (away blue `#1f77b4`, home orange `#ff7f0e`)
- Marker size scaled by `points` (freethrow=6, 2pt=10, 3pt=14)
- Horizontal zero line via `add_hline(y=0)`
- Vertical lines at quarter boundaries — use `add_shape` + `add_annotation` pattern
- Hover: team, points, period, score context (pre_lead → post_lead), Δprice, trades used
- Height: 340px, template: `plotly_dark`
- Return `_empty_score_figure()` if `sensitivity_df` is None or empty

**`build_sensitivity_surface(sensitivity_df, manifest, settings, title) -> go.Figure`**
- Two-row subplot figure:
  - **Top — By Quarter:** Grouped bar chart. X = period labels (Q1-Q4, OT+). Groups = lead bins (Close/Moderate/Blowout). Y = mean |Δprice|. Hover with event count, median Δprice.
  - **Bottom — By Time Bucket:** Same grouped bar structure. X = time bucket labels (e.g., "0-6 min", "6-12 min", ...). Groups = lead bins.
- Empty cells → absent bars (not zero)
- Color: Close=green, Moderate=yellow, Blowout=red (muted tones for dark theme)
- Height: 500px (two subplots)
- Return `_empty_score_figure()` if no data
- Events with `trades_before_count == 0` or `trades_after_count == 0`: reduced opacity to flag low-confidence data

---

### Step 4: Integrate into dashboard layout and callback
Files: pages/main_dashboard_page.py
Depends on: Step 3

**What changes:**
- **Layout:** Add two new `dcc.Graph` elements between Score Difference and In-Game charts:
  ```
  H3("Price Sensitivity to Scoring")
  dcc.Loading(dcc.Graph(id="sensitivity-timeline", style={"height": "360px"}))
  H3("Sensitivity by Game Phase & Lead")
  dcc.Loading(dcc.Graph(id="sensitivity-surface", style={"height": "520px"}))
  ```
- **Callback:** Add 2 new `Output` entries (total grows from 8 to 10)
- **Callback body:** After existing chart builds:
  ```python
  from sensitivity import load_or_compute_sensitivity
  from charts import build_sensitivity_timeline, build_sensitivity_surface

  cache_dir = Path(__file__).parent.parent / "cache"
  sensitivity_df = load_or_compute_sensitivity(
      cache_dir, date, match_id,
      trades_df, data["events"], manifest, settings
  )
  sensitivity_timeline_fig = build_sensitivity_timeline(
      sensitivity_df, manifest, data["events"]
  )
  sensitivity_surface_fig = build_sensitivity_surface(
      sensitivity_df, manifest, settings
  )
  ```
- **Return:** Add both figures to the return tuple

---

### Step 5: Tests for sensitivity computation and charts
Files: tests/test_sensitivity.py (new)
Depends on: Step 2, Step 3

**What changes:**
- New test file with:

**Computation tests:**
- `test_basic_sensitivity_computation` — 3 scoring events with known trades, verify delta_price values
- `test_lead_bin_classification` — events at various lead states, verify bin assignment
- `test_fewer_trades_than_window` — only 2 trades when window is 5, verify fallback
- `test_no_trades_after_event` — last event has no subsequent trades, verify None price_after
- `test_no_events_returns_none` — empty events returns None
- `test_freethrow_points` — verify freethrow events get points=1

**Caching tests:**
- `test_cache_write_and_read` — compute, verify file exists, reload, verify identical
- `test_cache_directory_creation` — verify missing cache dir is created

**Chart tests:**
- `test_timeline_empty_input` — None input returns empty figure
- `test_timeline_trace_count` — verify scatter traces
- `test_surface_subplot_structure` — verify two subplots
- `test_surface_empty_cells` — bins with no events have no bar

## Execution Preview

```
Wave 0 (1 agent):   Step 1 — Add sensitivity settings
Wave 1 (1 agent):   Step 2 — Sensitivity computation module
Wave 2 (1 agent):   Step 3 — Chart builders
Wave 3 (2 parallel): Step 4 — Dashboard integration
                     Step 5 — Tests

Critical path: Step 1 → Step 2 → Step 3 → Step 4 (4 waves)
Max parallelism: 2 agents (Wave 3)
```

## Risk Flags

- **`add_vline` trap:** Step 3 draws quarter boundary verticals — must use `add_shape` + `add_annotation` per HIGH-salience decision-log entry
- **Callback output count grows from 8 → 10:** Dash requires all outputs returned in order — any mismatch crashes the app. Step 4 must update both the decorator and the return tuple atomically.
- **Cache staleness:** If settings change (e.g., `sensitivity_price_window_trades` from 5 to 3), cached data becomes stale. Not handled in this plan — acceptable for prototype. Future: include settings hash in cache filename.
- **`.gitignore` update:** Step 2 adds `cache/` to `.gitignore` — verify the file exists first and append.

## Verification

1. Run `python -m pytest tests/ -v` — all existing + new tests pass
2. Launch app (`python app.py`), select an NBA game
3. Verify both new charts render below Score Difference
4. Verify `cache/{date}/{match_id}_sensitivity.json` is created
5. Reload same game — verify cache is read (no recomputation)
6. Select a non-NBA game — verify empty placeholder figures appear
