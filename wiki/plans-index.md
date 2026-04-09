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
