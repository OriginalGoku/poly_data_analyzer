"""Results export and visualization for the new per-position backtest schema."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import plotly.graph_objects as go


def export_backtest_results(
    per_position_df: pd.DataFrame,
    aggregation_df: pd.DataFrame,
    output_path: str = "backtest_results",
    heatmap_dims: Optional[Tuple[str, str]] = None,
    metric: str = "mean_roi_pct",
) -> None:
    """Export per-position + aggregation frames to CSV/JSON, plus optional heatmap.

    Args:
        per_position_df: One row per Position from the runner.
        aggregation_df: Grouped aggregation (scenario_name + sweep_axis_*).
        output_path: Output directory path.
        heatmap_dims: (row_dim, col_dim) column names from aggregation_df. If
            either is missing, falls back to a 1xN row using the present dim.
            If both missing, heatmap is skipped.
        metric: Column in aggregation_df to use as heatmap value.
    """
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)

    per_position_df.to_csv(out / "results_positions.csv", index=False)
    per_position_df.to_json(out / "results_positions.json", orient="records", indent=2)

    aggregation_df.to_csv(out / "results_aggregation.csv", index=False)
    aggregation_df.to_json(out / "results_aggregation.json", orient="records", indent=2)

    if heatmap_dims is not None and not aggregation_df.empty and metric in aggregation_df.columns:
        _render_heatmap(aggregation_df, heatmap_dims, metric, out / "roi_heatmap.html")


def _render_heatmap(
    df: pd.DataFrame,
    dims: Tuple[str, str],
    metric: str,
    out_file: Path,
) -> None:
    row_dim, col_dim = dims
    have_row = row_dim in df.columns
    have_col = col_dim in df.columns

    if not have_row and not have_col:
        return

    try:
        if have_row and have_col:
            pivoted = df.pivot_table(
                index=row_dim, columns=col_dim, values=metric, aggfunc="mean"
            )
            x_labels = list(pivoted.columns)
            y_labels = list(pivoted.index)
            z = pivoted.values
            x_title, y_title = col_dim, row_dim
        else:
            present = row_dim if have_row else col_dim
            grouped = df.groupby(present, dropna=False)[metric].mean()
            x_labels = list(grouped.index)
            y_labels = [metric]
            z = [grouped.values]
            x_title, y_title = present, metric

        fig = go.Figure(
            data=go.Heatmap(z=z, x=x_labels, y=y_labels, colorscale="RdYlGn")
        )
        fig.update_layout(
            title=f"{metric} heatmap",
            xaxis_title=x_title,
            yaxis_title=y_title,
        )
        fig.write_html(str(out_file))
    except Exception:
        pass
