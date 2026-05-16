## Lens status

Single-lens (no `/review` or `/brainstorm` performed). `/probe` ran before this plan; findings incorporated.

## Problem Statement

Game `nba-tor-cle-2026-05-03` shows in the main dashboard game list with 2 trades / $5.38 total volume — a truncated upstream download is silently presented as a normal game. Two gaps:

1. `pregame_min_cum_vol` (default 5,000) is only consumed by `_meaningful_open_snapshot` (analytics.py:533) as the open-anchor threshold. It is NOT applied as a universe gate — low-volume games still populate the game-picker.
2. Even above the gate, thin games (e.g., 10k–20k pregame volume) should be visually flagged so the user knows the underlying trades feed is suspect.

User decisions (from `/probe` follow-up):
- Reuse the single `pregame_min_cum_vol` knob as the hard gate (no second knob).
- Add a separate soft threshold for the warning badge (default 20,000).
- Signal: `pre_game_notional_usdc` primary; badge also looks at `trade_count`.

## Codebase Context

### Reusable-Code Survey

Searched: `analytics.py`, `pages/main_dashboard_page.py`, `settings.py`, `chart_settings.json`, `loaders.py`. No graphify or repo-index present.

- `analytics._build_game_record` (analytics.py:473) — already projects one `volume_stats` field (`in_game_notional_usdc`, line 508). Pattern reused to add `pre_game_notional_usdc` and `trade_count`.
- `analytics.get_analytics_view` post-cache filter pattern (analytics.py:146-159) — `sport`/`price_quality`/`start_date`/`end_date` are applied as post-cache row masks after `_load_game_analytics_cached`. Same shape used for the new vol gate; no new cache key dimension.
- `populate_games` callback (pages/main_dashboard_page.py:215-247) — existing site for `bucket` filter (line 229-230). New gate sits at the same point; "filtered count" computed by `len(before) - len(after)`.
- `_build_game_card` (pages/main_dashboard_page.py:453-463) — already reads `volume.get("trade_count")` and `total_notional_usdc`. Natural place for badge; sibling to existing `Truncated` info_row.
- `ChartSettings` dataclass (settings.py) + `info_row` Chart Settings UI block (pages/main_dashboard_page.py:140-160) — pattern for new setting field.

### External surfaces

None — change is local Python + Dash. No CLI / API contracts.

## Pre-Change Baseline

- `nba-tor-cle-2026-05-03` is listed in the game-picker for sport=nba on date 2026-05-03 despite `volume_stats.pre_game_notional_usdc = 5.38`.
- `chart_settings.json:7` has `pregame_min_cum_vol: 5000`.
- Game-card for any low-volume game shows raw `Trades: 2` / `Total Volume: $5` without visual flag — user must read numbers.
- Test suite: `tests/test_analytics.py`, `tests/test_stream_game_analytics.py` currently green.

## Verification Signal

- `nba-tor-cle-2026-05-03` no longer appears in the game-picker when `pregame_min_cum_vol = 5000` (it has $5.38 pregame notional, well below).
- Setting `pregame_min_cum_vol = 0` restores it.
- Any game with `pre_game_notional_usdc >= 5000` but `< 20000` (or `trade_count < N_low`) shows a visible warning badge in the game-card.
- The dashboard surfaces a `Filtered N games (below $X pregame vol)` counter (placement TBD — see Open Questions).
- New unit tests cover: (a) base-record now includes `pre_game_notional_usdc` and `trade_count`; (b) `get_analytics_view` excludes rows below the gate when a new `min_pregame_notional` arg is set; (c) badge rendering helper returns the warning element for thin games and `None` otherwise.

## Implementation Steps

### Step 1: Project pregame-volume fields into base records
Files: analytics.py, tests/test_analytics.py
Depends on: none

**What changes:**
- In `_build_game_record` (analytics.py:473), add to the returned dict: `"pre_game_notional_usdc": manifest.get("volume_stats", {}).get("pre_game_notional_usdc")` and `"trade_count": manifest.get("volume_stats", {}).get("trade_count")`. Mirror the `in_game_notional_usdc` line (analytics.py:508) — same null-safe pattern.
- Both fields are nullable; downstream code must handle `None` (treat as 0 for gate comparison; treat as "unknown" for badge — do not flag if missing).

**Test strategy:**
- Extend `tests/test_analytics.py::TestAnalytics::test_loads_multi_sport_game_records` (or add a sibling test) to assert the new columns exist on the returned frame and carry through from a manifest that includes `volume_stats.pre_game_notional_usdc` and `volume_stats.trade_count`.

### Step 2: Add `data_warning_min_pregame_vol` setting
Files: settings.py, chart_settings.json, pages/main_dashboard_page.py
Depends on: none

**What changes:**
- `settings.py`: add `data_warning_min_pregame_vol: float = 20000` to `ChartSettings` dataclass; add corresponding line to `to_dict()`.
- `chart_settings.json`: add `"data_warning_min_pregame_vol": 20000` key.
- `pages/main_dashboard_page.py` Chart Settings UI block (~line 148): add a new `info_row("Data Warning Min Vol", f"${settings_dict['data_warning_min_pregame_vol']:,}")` immediately after the existing `Pre-Game Min Cum Vol` row.
- No filter logic in this step — purely surfaces the setting.

**Test strategy:**
- `ChartSettings.from_dict({...})` roundtrip already covered indirectly via `load_chart_settings`. Add a small unit assertion (or extend an existing test if one exists) that `ChartSettings().data_warning_min_pregame_vol == 20000`.
- Manual: load app, verify the new row renders in the Chart Settings card.

### Step 3: Apply hard pregame-volume gate in game-picker
Files: pages/main_dashboard_page.py, analytics.py, tests/test_analytics.py
Depends on: Step 1, Step 2

**What changes:**
- `analytics.get_analytics_view`: add `min_pregame_notional: float = 0` kwarg. After the existing `start_date`/`end_date`/`price_quality` masks (analytics.py:149-159), apply `view = view[view["pre_game_notional_usdc"].fillna(0) >= min_pregame_notional].copy()` (treat missing as 0 → excluded if any positive gate is set). Apply BEFORE `_compute_quantile_thresholds` so bands are computed from gated universe.
- `pages/main_dashboard_page.py::populate_games`: pass `min_pregame_notional=settings_dict.get("pregame_min_cum_vol", 0)` into `get_analytics_view`. Capture the row count before/after the bucket filter; compute total filtered count vs. the un-gated baseline (a second call with `min_pregame_notional=0` is acceptable since `_load_game_analytics_cached` memoizes; alternatively compute from the cached frame directly to avoid the second pass).
- Surface "Filtered N games (< $X pregame vol)" as a small note. Default placement: a `dcc.Markdown` row directly below the game-picker dropdown. Alternative placement: inside the Chart Settings card. Locked in Open Questions.

**Test strategy:**
- Add `tests/test_analytics.py::test_get_analytics_view_min_pregame_notional_gate`: build a frame with 3 games (volumes 100, 5_000, 50_000), assert `min_pregame_notional=5000` returns 2 games and `=0` returns 3.
- Manual: with default settings on `2026-05-03`, confirm `nba-tor-cle` no longer appears and a "Filtered: 1 game" note shows.

### Step 4: Add data-quality warning badge to game-card
Files: pages/main_dashboard_page.py, tests/test_main_dashboard_page.py
Depends on: Step 2, Step 3

**What changes:**
- In `_build_game_card` block (pages/main_dashboard_page.py:453-463), compute `pregame_vol = volume.get("pre_game_notional_usdc")` and `trade_count = volume.get("trade_count")`. If `pregame_vol is not None and pregame_vol < settings_dict["data_warning_min_pregame_vol"]` OR `trade_count is not None and trade_count < 50` (constant for the trade-count secondary signal — see Open Questions), prepend a visible badge: e.g. `html.Div("⚠ Likely truncated trade data — pregame volume $X (< $Y threshold)", style={"backgroundColor": "#5a2222", "color": "#fff", "padding": "6px 10px", "borderRadius": "4px", "marginBottom": "8px", "fontWeight": "bold"})`.
- Pass `settings_dict` into the inner callback closure if not already in scope (it already is — defined at line 186).
- Badge ONLY shows when the game survives the gate (post-Step 3); games below the gate aren't in the picker at all.

**Test strategy:**
- New file `tests/test_main_dashboard_page.py` (or extend existing if present): extract the badge-builder into a small pure helper (e.g., `_build_data_warning_badge(volume_stats, soft_threshold) -> html.Div | None`) to make it testable. Assert: thin game returns a Div; healthy game returns None; missing field returns None.
- Manual: pick a borderline game ($5k–$20k pregame vol) and verify the red badge renders at the top of the game-card.

### Step 5: Documentation + CLAUDE.md note
Files: CLAUDE.md
Depends on: Step 1, Step 2, Step 3, Step 4

**What changes:**
- Update the `## Key Patterns` section in CLAUDE.md to note: (a) `pregame_min_cum_vol` now serves dual purpose — open-anchor threshold AND main-dashboard game-list hard gate; (b) `data_warning_min_pregame_vol` is the soft-threshold warning badge in the game-card.
- One-line entry in the `### Dashboard & Analytics` block under `analytics.py` mentioning the new projected `pre_game_notional_usdc` / `trade_count` columns.

**Test strategy:**
- N/A — doc-only.

## Execution Preview

| Wave | Steps | Files touched | Parallelism |
|---|---|---|---|
| 0 | 1, 2 | analytics.py, settings.py, chart_settings.json, pages/main_dashboard_page.py (UI block), tests/test_analytics.py | 2 |
| 1 | 3 | analytics.py, pages/main_dashboard_page.py (callback), tests/test_analytics.py | 1 |
| 2 | 4 | pages/main_dashboard_page.py (game-card), tests/test_main_dashboard_page.py | 1 |
| 3 | 5 | CLAUDE.md | 1 |

Total waves: 4. Critical path: 1 → 3 → 4 → 5. Note: Steps 2 and 3 both edit `pages/main_dashboard_page.py` but in different blocks (UI definition vs. callback); explicit dep Step 3→Step 2 prevents merge friction.

## Risk Flags

- **`data_warning_min_pregame_vol` and `pregame_min_cum_vol` semantics drift.** Both target pregame volume but compare to different things: the gate reads `manifest.volume_stats.pre_game_notional_usdc` (USDC notional); the open-anchor reads cumulative trade `size` (share count, see `_filter_by_min_cum_vol`). Same name, different units. Acceptable for now (user accepted the dual-use), but flag in CLAUDE.md so future readers don't assume they're identical comparators.
- **Trade-count secondary threshold (Step 4) is a hardcoded constant (`50`).** Could become a config setting if it turns out to need tuning; leave as constant initially to avoid setting sprawl.
- **No sentrux gate run in this plan** since the change is small and constrained to known files; `/architecture-gate compare` can be invoked manually post-implementation if desired.
- **Cache invalidation.** New fields in `_build_game_record` will appear on existing cached `_base_records/<settings_hash>.pkl` only on cache-miss. Since the cache key includes `pregame_min_cum_vol`, no key change is needed, but existing cached pickles won't have `pre_game_notional_usdc` until rebuild. Mitigation: bump the settings_hash inputs (add a schema marker) OR document the need to delete `cache/_base_records/` once. Recommend the latter — single cache-clear is simpler than a versioning scheme.

## Open Questions

- **Filtered-count placement.** Below the game-picker dropdown (more visible, contextually adjacent) vs. inside the Chart Settings card (consolidates filter UI). Recommendation: below dropdown — user is most likely to notice missing games at the picker, not in the settings card. Confirm before Step 3 implementation.

## Verification

- `pytest tests/test_analytics.py tests/test_main_dashboard_page.py tests/test_stream_game_analytics.py -v` passes.
- Manual: run `python app.py`, navigate to `http://127.0.0.1:8050/`, set date range to 2026-05-03, confirm:
  - `nba-tor-cle-2026-05-03` no longer in picker
  - "Filtered: 1 game (< $5,000)" note visible
  - Setting `pregame_min_cum_vol = 0` in `chart_settings.json` + reload → game reappears
  - Selecting a game with pregame vol between $5k–$20k shows the red warning badge atop game-card.
- Delete `cache/_base_records/` once after Step 1 lands so the projected fields populate on next analytics load.

## Save-time amendments

Captured at: 2026-05-16
Source: `/save-plan` arguments
Note: amendments are audit-only provenance. `/execute-plan` reads `## Implementation Steps` only. If an amendment alters Step contracts (files / deps / structure), re-run `/technical-plan` before `/execute-plan`.

- agree to place the Filtered-count below the dropdown but also in the setting cards


<!-- toolkit: check=clean waves=clean gate=fired:open-questions -->
