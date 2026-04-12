# Plan: Price Dip Recovery Analysis — Single-Game View

## Context

The main dashboard currently has sensitivity analysis (per-scoring-event price deltas) and market-score discrepancy intervals. We want to add three new analysis features to the single-game view to study price recovery patterns, validate the data is clean, then later aggregate cross-game.

Three features were agreed upon during probe:
1. Extend existing discrepancy intervals with forward-return metrics
2. Absolute threshold price dip detection (2-5% probability)
3. Regime-conditioned forward returns (band transitions)

---

## Implementation Order

### Step 0: Data Prevalence Check (Feature 2 validation)

**Goal:** Determine how many games have in-game prices below 2%, 3%, 4%, 5% before building Feature 2.

- **Create:** `scripts/check_dip_prevalence.py`
- Scan all collected games, filter to in-game trades (after tipoff), count games where either team's price drops below each threshold
- Output: table of threshold → game count, total dip events, avg dips per game
- Quick standalone script, no integration needed
- **Decision gate:** If counts are trivially low at some thresholds, we can still build the feature but will know which thresholds are statistically meaningful

### Step 1: Extend Discrepancy Intervals (Feature 1)

**Scope:** Smallest change — adds time-bounded forward-return metrics to existing discrepancy intervals.

#### Files to modify:
- `discrepancy.py` — add forward-return fields to `_summarize_lead_interval()` and `_summarize_tie_interval()`
- `chart_settings.json` — add `discrepancy_forward_return_horizon_minutes` (default: 12)
- `settings.py` — add field to `ChartSettings`
- `charts.py` — update `build_discrepancy_intervals_chart()` hover template to show new fields
- `pages/main_dashboard_page.py` — no structural changes (data flows through existing discrepancy pipeline)

#### New fields on each discrepancy interval:
- `forward_max_price` — max favorable price within horizon from interval start
- `forward_max_time_seconds` — time to reach that max (seconds from interval start)
- `forward_return` — `forward_max_price - price_start`
- `forward_return_pct` — percentage return relative to initial price

#### Implementation details:
- In `_summarize_lead_interval()`: after computing existing metrics, look forward from interval start through `aligned` DataFrame up to `start_time + horizon_minutes`
- Track the undervalued side's price (same logic as existing `price_series` selection)
- Same pattern for `_summarize_tie_interval()`: track distance-from-0.5 reversion within horizon
- **Cache:** Bump `DISCREPANCY_CACHE_SCHEMA_VERSION` from 4 → 5 (invalidates existing cache, forces recompute)
- Add fields to `_cache_has_required_columns()` required set

#### Chart changes:
- Add forward-return fields to hover template in `build_discrepancy_intervals_chart()`
- No new chart — just richer hover data on existing discrepancy chart

### Step 2: Regime-Conditioned Forward Returns (Feature 3)

**Scope:** New computation module + chart. Detects interpretable band transitions during in-game play and measures forward returns.

#### Files to create:
- `regime_transitions.py` — computation + cache module

#### Files to modify:
- `chart_settings.json` — add `regime_forward_horizon_minutes` (default: 12), `regime_min_trades_in_window` (default: 3), `regime_max_trade_gap_seconds` (default: 120)
- `settings.py` — add fields to `ChartSettings`
- `charts.py` — add `build_regime_transitions_chart()` function
- `pages/main_dashboard_page.py` — add chart to layout + callback

#### Computation (`regime_transitions.py`):
- **Input:** `trades_df`, `events`, `manifest`, `settings`
- Use favorite-side price (per CLAUDE.md: "regime analytics should be built from favorite-side probabilities")
- Assign each in-game trade's favorite-side price to an interpretable band using `analytics._assign_interpretable_band()`
- Detect band transitions: when consecutive trades fall in different bands
- For each transition event:
  - `transition_time`, `from_band`, `to_band`, `price_at_transition`
  - `period` (quarter), `seconds_since_tipoff`, `time_bin`
  - Forward metrics within horizon: `forward_max_price`, `forward_min_price`, `forward_return_max`, `forward_time_to_max_seconds`
  - Quality flags: `trades_in_window` count, `low_confidence` flag
- **Debouncing:** Require at least N trades confirming the new band before registering a transition (avoids single-trade flickers)
- **Cache pattern:** `load_or_compute_regime_transitions()`, cache as `{match_id}_regime_transitions.json`, with schema version

#### Chart (`build_regime_transitions_chart()`):
- 2-row subplot (reuse `build_sensitivity_surface()` pattern):
  - Row 1: By Quarter — grouped bars showing mean forward return by `from_band → to_band` direction (upgrade vs downgrade)
  - Row 2: By Time Bucket — same metric by 6-minute bins
- Color-code by transition direction: upgrades (green), downgrades (red)
- Low-confidence events shown with reduced opacity (same pattern as sensitivity surface)

#### Dashboard integration:
- Add `dcc.Loading(dcc.Graph(id="regime-transitions-chart"))` to layout after discrepancy chart
- Add `load_or_compute_regime_transitions()` call in `update_game` callback
- Add `build_regime_transitions_chart()` call
- Add output to callback return tuple

### Step 3: Absolute Threshold Dip Detection (Feature 2)

**Scope:** New computation module + chart. Detects when prices cross below absolute thresholds and tracks recovery.

**Prerequisite:** Step 0 prevalence check results reviewed.

#### Files to create:
- `dip_recovery.py` — computation + cache module

#### Files to modify:
- `chart_settings.json` — add `dip_thresholds` (default: `[0.05, 0.04, 0.03, 0.02]`), `dip_min_trades` (default: 3), `dip_max_trade_gap_seconds` (default: 120), `dip_recovery_horizon_minutes` (default: 15)
- `settings.py` — add fields to `ChartSettings` (note: `dip_thresholds` is a list, needs special handling in frozen dataclass — use `tuple` type)
- `charts.py` — add `build_dip_recovery_chart()` function
- `pages/main_dashboard_page.py` — add chart to layout + callback

#### Computation (`dip_recovery.py`):
- **Input:** `trades_df`, `events`, `manifest`, `settings`
- Filter to in-game trades (after tipoff, before game_end + buffer)
- For each team's token, scan price series against each threshold
- **Interval model (matching discrepancy.py pattern):**
  - Detect first crossing below threshold → start of dip interval
  - Interval ends when price returns above threshold OR max trade gap exceeded OR game ends
  - Group via cumsum on state transitions (same as `discrepancy.py` interval_id)
  - Require min trades within interval
- **Per dip interval record:**
  - `team`, `threshold`, `entry_time`, `exit_time`, `duration_seconds`
  - `period`, `seconds_since_tipoff`, `time_bin`
  - `min_price` (deepest point in dip)
  - `max_recovery_price` — max price reached before returning to or below threshold
  - `recovery_magnitude` — `max_recovery_price - min_price`
  - `recovery_pct` — percentage recovery relative to threshold
  - `time_to_max_recovery_seconds`
  - `trade_count`, `low_confidence` flag
  - `resolution`: `recovered` (crossed back above threshold), `remained_below`, `game_ended`
- **Cache:** `{match_id}_dip_recovery.json`, schema versioned

#### Chart (`build_dip_recovery_chart()`):
- 2-row subplot (same "By Quarter / By Time Bucket" layout):
  - Row 1: By Quarter — scatter or grouped bars showing recovery magnitude by threshold, colored by threshold level
  - Row 2: By Time Bucket — same metric by 6-minute bins
- If no dip events found for a game, show empty state message
- Color scale by threshold: deeper thresholds = more intense color

#### Dashboard integration:
- Add `dcc.Loading(dcc.Graph(id="dip-recovery-chart"))` to layout
- Add to `update_game` callback (same pattern as sensitivity/discrepancy)

---

## Settings Summary

New entries in `chart_settings.json`:
```json
{
  "discrepancy_forward_return_horizon_minutes": 12,
  "regime_forward_horizon_minutes": 12,
  "regime_min_trades_in_window": 3,
  "regime_max_trade_gap_seconds": 120,
  "dip_thresholds": [0.05, 0.04, 0.03, 0.02],
  "dip_min_trades": 3,
  "dip_max_trade_gap_seconds": 120,
  "dip_recovery_horizon_minutes": 15
}
```

---

## Dashboard Layout Order (after changes)

1. Pre-Game chart
2. Score Progression
3. Lead Difference
4. Price Sensitivity to Scoring (timeline)
5. Sensitivity by Game Phase & Score Gap (surface)
6. Market-Score Discrepancies (existing, enriched hover)
7. **Regime Band Transitions** (new — Feature 3)
8. **Price Dip Recovery** (new — Feature 2)
9. In-Game chart

---

## Files Modified/Created Summary

| File | Action | Feature |
|---|---|---|
| `scripts/check_dip_prevalence.py` | Create | Step 0 |
| `discrepancy.py` | Modify | Feature 1 |
| `regime_transitions.py` | Create | Feature 3 |
| `dip_recovery.py` | Create | Feature 2 |
| `charts.py` | Modify | Features 1, 2, 3 |
| `chart_settings.json` | Modify | Features 1, 2, 3 |
| `settings.py` | Modify | Features 1, 2, 3 |
| `pages/main_dashboard_page.py` | Modify | Features 2, 3 |

---

## Verification

After each feature:
1. Run the app (`python app.py`), select a game with known events
2. Verify new charts render (or show appropriate empty states for games without qualifying events)
3. Check cache files are created in `cache/{date}/`
4. Delete cache, reload — verify recomputation produces identical results
5. Test with games that have sparse in-game trades (edge case for quality gates)
6. For Feature 2: compare prevalence script output against what the chart shows for individual games

```


**Tool Call: ToolSearch**
Status: Completed

Tool: ExitPlanMode

**Tool Call: Ready to code?**
Status: Canceled

# Plan: Price Dip Recovery Analysis — Single-Game View

## Context

The main dashboard currently has sensitivity analysis (per-scoring-event price deltas) and market-score discrepancy intervals. We want to add three new analysis features to the single-game view to study price recovery patterns, validate the data is clean, then later aggregate cross-game.

Three features were agreed upon during probe:
1. Extend existing discrepancy intervals with forward-return metrics
2. Absolute threshold price dip detection (2-5% probability)
3. Regime-conditioned forward returns (band transitions)

---

## Implementation Order

### Step 0: Data Prevalence Check (Feature 2 validation)

**Goal:** Determine how many games have in-game prices below 2%, 3%, 4%, 5% before building Feature 2.

- **Create:** `scripts/check_dip_prevalence.py`
- Scan all collected games, filter to in-game trades (after tipoff), count games where either team's price drops below each threshold
- Output: table of threshold → game count, total dip events, avg dips per game
- Quick standalone script, no integration needed
- **Decision gate:** If counts are trivially low at some thresholds, we can still build the feature but will know which thresholds are statistically meaningful

### Step 1: Extend Discrepancy Intervals (Feature 1)

**Scope:** Smallest change — adds time-bounded forward-return metrics to existing discrepancy intervals.

#### Files to modify:
- `discrepancy.py` — add forward-return fields to `_summarize_lead_interval()` and `_summarize_tie_interval()`
- `chart_settings.json` — add `discrepancy_forward_return_horizon_minutes` (default: 12)
- `settings.py` — add field to `ChartSettings`
- `charts.py` — update `build_discrepancy_intervals_chart()` hover template to show new fields
- `pages/main_dashboard_page.py` — no structural changes (data flows through existing discrepancy pipeline)

#### New fields on each discrepancy interval:
- `forward_max_price` — max favorable price within horizon from interval start
- `forward_max_time_seconds` — time to reach that max (seconds from interval start)
- `forward_return` — `forward_max_price - price_start`
- `forward_return_pct` — percentage return relative to initial price

#### Implementation details:
- In `_summarize_lead_interval()`: after computing existing metrics, look forward from interval start through `aligned` DataFrame up to `start_time + horizon_minutes`
- Track the undervalued side's price (same logic as existing `price_series` selection)
- Same pattern for `_summarize_tie_interval()`: track distance-from-0.5 reversion within horizon
- **Cache:** Bump `DISCREPANCY_CACHE_SCHEMA_VERSION` from 4 → 5 (invalidates existing cache, forces recompute)
- Add fields to `_cache_has_required_columns()` required set

#### Chart changes:
- Add forward-return fields to hover template in `build_discrepancy_intervals_chart()`
- No new chart — just richer hover data on existing discrepancy chart

### Step 2: Regime-Conditioned Forward Returns (Feature 3)

**Scope:** New computation module + chart. Detects interpretable band transitions during in-game play and measures forward returns.

#### Files to create:
- `regime_transitions.py` — computation + cache module

#### Files to modify:
- `chart_settings.json` — add `regime_forward_horizon_minutes` (default: 12), `regime_min_trades_in_window` (default: 3), `regime_max_trade_gap_seconds` (default: 120)
- `settings.py` — add fields to `ChartSettings`
- `charts.py` — add `build_regime_transitions_chart()` function
- `pages/main_dashboard_page.py` — add chart to layout + callback

#### Computation (`regime_transitions.py`):
- **Input:** `trades_df`, `events`, `manifest`, `settings`
- Use favorite-side price (per CLAUDE.md: "regime analytics should be built from favorite-side probabilities")
- Assign each in-game trade's favorite-side price to an interpretable band using `analytics._assign_interpretable_band()`
- Detect band transitions: when consecutive trades fall in different bands
- For each transition event:
  - `transition_time`, `from_band`, `to_band`, `price_at_transition`
  - `period` (quarter), `seconds_since_tipoff`, `time_bin`
  - Forward metrics within horizon: `forward_max_price`, `forward_min_price`, `forward_return_max`, `forward_time_to_max_seconds`
  - Quality flags: `trades_in_window` count, `low_confidence` flag
- **Debouncing:** Require at least N trades confirming the new band before registering a transition (avoids single-trade flickers)
- **Cache pattern:** `load_or_compute_regime_transitions()`, cache as `{match_id}_regime_transitions.json`, with schema version

#### Chart (`build_regime_transitions_chart()`):
- 2-row subplot (reuse `build_sensitivity_surface()` pattern):
  - Row 1: By Quarter — grouped bars showing mean forward return by `from_band → to_band` direction (upgrade vs downgrade)
  - Row 2: By Time Bucket — same metric by 6-minute bins
- Color-code by transition direction: upgrades (green), downgrades (red)
- Low-confidence events shown with reduced opacity (same pattern as sensitivity surface)

#### Dashboard integration:
- Add `dcc.Loading(dcc.Graph(id="regime-transitions-chart"))` to layout after discrepancy chart
- Add `load_or_compute_regime_transitions()` call in `update_game` callback
- Add `build_regime_transitions_chart()` call
- Add output to callback return tuple

### Step 3: Absolute Threshold Dip Detection (Feature 2)

**Scope:** New computation module + chart. Detects when prices cross below absolute thresholds and tracks recovery.

**Prerequisite:** Step 0 prevalence check results reviewed.

#### Files to create:
- `dip_recovery.py` — computation + cache module

#### Files to modify:
- `chart_settings.json` — add `dip_thresholds` (default: `[0.05, 0.04, 0.03, 0.02]`), `dip_min_trades` (default: 3), `dip_max_trade_gap_seconds` (default: 120), `dip_recovery_horizon_minutes` (default: 15)
- `settings.py` — add fields to `ChartSettings` (note: `dip_thresholds` is a list, needs special handling in frozen dataclass — use `tuple` type)
- `charts.py` — add `build_dip_recovery_chart()` function
- `pages/main_dashboard_page.py` — add chart to layout + callback

#### Computation (`dip_recovery.py`):
- **Input:** `trades_df`, `events`, `manifest`, `settings`
- Filter to in-game trades (after tipoff, before game_end + buffer)
- For each team's token, scan price series against each threshold
- **Interval model (matching discrepancy.py pattern):**
  - Detect first crossing below threshold → start of dip interval
  - Interval ends when price returns above threshold OR max trade gap exceeded OR game ends
  - Group via cumsum on state transitions (same as `discrepancy.py` interval_id)
  - Require min trades within interval
- **Per dip interval record:**
  - `team`, `threshold`, `entry_time`, `exit_time`, `duration_seconds`
  - `period`, `seconds_since_tipoff`, `time_bin`
  - `min_price` (deepest point in dip)
  - `max_recovery_price` — max price reached before returning to or below threshold
  - `recovery_magnitude` — `max_recovery_price - min_price`
  - `recovery_pct` — percentage recovery relative to threshold
  - `time_to_max_recovery_seconds`
  - `trade_count`, `low_confidence` flag
  - `resolution`: `recovered` (crossed back above threshold), `remained_below`, `game_ended`
- **Cache:** `{match_id}_dip_recovery.json`, schema versioned

#### Chart (`build_dip_recovery_chart()`):
- 2-row subplot (same "By Quarter / By Time Bucket" layout):
  - Row 1: By Quarter — scatter or grouped bars showing recovery magnitude by threshold, colored by threshold level
  - Row 2: By Time Bucket — same metric by 6-minute bins
- If no dip events found for a game, show empty state message
- Color scale by threshold: deeper thresholds = more intense color

#### Dashboard integration:
- Add `dcc.Loading(dcc.Graph(id="dip-recovery-chart"))` to layout
- Add to `update_game` callback (same pattern as sensitivity/discrepancy)

---

## Settings Summary

New entries in `chart_settings.json`:
```json
{
  "discrepancy_forward_return_horizon_minutes": 12,
  "regime_forward_horizon_minutes": 12,
  "regime_min_trades_in_window": 3,
  "regime_max_trade_gap_seconds": 120,
  "dip_thresholds": [0.05, 0.04, 0.03, 0.02],
  "dip_min_trades": 3,
  "dip_max_trade_gap_seconds": 120,
  "dip_recovery_horizon_minutes": 15
}
```

---

## Dashboard Layout Order (after changes)

1. Pre-Game chart
2. Score Progression
3. Lead Difference
4. Price Sensitivity to Scoring (timeline)
5. Sensitivity by Game Phase & Score Gap (surface)
6. Market-Score Discrepancies (existing, enriched hover)
7. **Regime Band Transitions** (new — Feature 3)
8. **Price Dip Recovery** (new — Feature 2)
9. In-Game chart

---

## Files Modified/Created Summary

| File | Action | Feature |
|---|---|---|
| `scripts/check_dip_prevalence.py` | Create | Step 0 |
| `discrepancy.py` | Modify | Feature 1 |
| `regime_transitions.py` | Create | Feature 3 |
| `dip_recovery.py` | Create | Feature 2 |
| `charts.py` | Modify | Features 1, 2, 3 |
| `chart_settings.json` | Modify | Features 1, 2, 3 |
| `settings.py` | Modify | Features 1, 2, 3 |
| `pages/main_dashboard_page.py` | Modify | Features 2, 3 |

---

## Verification

After each feature:
1. Run the app (`python app.py`), select a game with known events
2. Verify new charts render (or show appropriate empty states for games without qualifying events)
3. Check cache files are created in `cache/{date}/`
4. Delete cache, reload — verify recomputation produces identical results
5. Test with games that have sparse in-game trades (edge case for quality gates)
6. For Feature 2: compare prevalence script output against what the chart shows for individual games
