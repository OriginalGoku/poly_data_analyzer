# Plans Index
<!-- Auto-maintained by /save-plan. Do not edit manually. -->

## [plan_file: NBA_Game_Visualizer_Plan.md] 2026-04-08
**Summary:** Dash+Plotly single-game viewer for NBA Polymarket trade data with game event overlays and key market timestamps.
**Key decisions:**
- Dash+Plotly over Streamlit for richer chart interactivity and synced zoom
- NBA-only, single game view (NHL/MLB and multi-game deferred)
- No bid/ask spread visualization — focus on executed trade data as-is
- First event `time_actual` as tip-off anchor (more accurate than `gamma_start_time`)

---

## [plan_file: Whale_Tracker_Plan.md] 2026-04-10
**Summary:** Add whale wallet identification, classification (Market Maker / Directional / Hybrid), and visualization to the NBA game viewer.
**Key decisions:**
- Side attribution is taker-only — buy/sell direction only meaningful for the trade aggressor
- Scatter line overlay instead of bar overlay to avoid barmode="stack" conflict
- Two separate leaderboards (Aggressors + Liquidity) instead of one blended list
- Volume denominator is single-counted trade volume for intuitive percentages

---

## [plan_file: Price_Sensitivity_Plan.md] 2026-04-11
**Summary:** Compute per-event price reactions to scoring plays and visualize as a timeline scatter and binned sensitivity surface, with per-game disk caching.
**Key decisions:**
- Cache in local `cache/` directory, not game data folder (data/ is a symlink to upstream)
- VWAP of 5 trades before/after each event (configurable), not simple mean
- 3 lead bins (Close 0-5, Moderate 6-12, Blowout 13+) with configurable thresholds
- Both quarter-based and time-based (6-min buckets) phase views in sensitivity surface

---

## [plan_file: Backtest_Correctness_Fixes_Plan.md] 2026-04-14
**Summary:** Fix six confirmed bugs in the backtest engine: look-ahead bias in exits, zero-PnL silent losses, one-sided fee, gross/net ROI confusion, broken time_based_quarter (removed), and baseline fee model mismatch.
**Key decisions:**
- Not-triggered exits use forced-close at last in-game price (not excluded from ROI mean)
- time_based_quarter removed entirely (three compounding bugs, no active users)
- Two-sided fee: (entry_price + exit_price) * fee_pct applied in compute_trade_pnl()
- Baselines inherit fee_model from config instead of hardcoding "taker"

---
