# CLAUDE.md

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                     # run Dash app on localhost:8050
```

## Structure

- `app.py` -- Dash app entry point (layout + callbacks)
- `charts.py` -- Plotly figure builders
- `loaders.py` -- Data loading and parsing
- `DATA_SPEC.md` -- Upstream data format reference (from poly-data-downloader)
- `data/` -- Trade data directories (YYYY-MM-DD format, not checked in)

## Key Patterns

- Data comes from `poly-data-downloader` -- see `DATA_SPEC.md` for schema
- `outcomes[0]` / `token_ids[0]` = away team, `[1]` = home team
- NBA events use `time_actual` (UTC wall-clock), directly comparable to trade timestamps
- Tricode-to-team mapping is built dynamically from score changes in events (no static lookup)
- `gamma_start_time` is scheduled start (can be ~12 min off); first event `time_actual` is actual tip-off
- Use `add_shape` + `add_annotation` for vertical lines on Plotly subplots (not `add_vline`)
