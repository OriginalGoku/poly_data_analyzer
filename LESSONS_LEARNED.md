# Lessons Learned

- Plotly `add_vline` with `annotation_text` silently fails on subplots with datetime x-axes. Use `add_shape` + `add_annotation` directly instead.
- Whale side attribution should use taker trades only -- maker trades are passive and don't indicate directional intent. A wallet that provides liquidity on both sides would appear "Mixed" incorrectly if maker trades were included.
- Wallet classification thresholds (maker % for Market Maker, minimum trade count) need to be configurable -- different markets have different liquidity profiles. Externalizing to `chart_settings.json` avoids hardcoding assumptions.
- Whale leaderboards need separate inclusion rules for aggressors vs liquidity providers -- qualifying as a whale on total volume is not enough to belong in a taker-only leaderboard.
- Cross-game analytics should come from a cached game-level table, not ad hoc scans inside UI callbacks. Otherwise sport filters and regime bands turn into repeated archive walks.
- For regime analysis, raw checkpoint opening prices can be too noisy. Re-anchoring "open" to the first pregame trade after cumulative volume reaches a minimum threshold produces a more defensible market-open proxy.
- Per-event sensitivity should be cached by game once computed. Replaying the same game in the dashboard should reload `cache/{date}/{match_id}_sensitivity.json` instead of recomputing VWAP windows on every callback.
