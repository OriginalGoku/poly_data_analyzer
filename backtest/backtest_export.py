"""Results export and visualization for backtest."""
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def export_backtest_results(
    aggregated_df: pd.DataFrame,
    per_game_df: pd.DataFrame,
    output_dir: str = "backtest_results",
    config: Optional[Dict] = None,
) -> None:
    """Export backtest results to CSV, JSON, and visualizations.

    Args:
        aggregated_df: Aggregated results (one row per strategy)
        per_game_df: Per-game results (all individual trades)
        output_dir: Output directory path
        config: Optional config dict with metadata (date range, etc.)
    """
    Path(output_dir).mkdir(exist_ok=True)

    # Export aggregated results
    aggregated_df.to_csv(f"{output_dir}/results_aggregated.csv", index=False)
    aggregated_df.to_json(f"{output_dir}/results_aggregated.json", orient="records", indent=2)

    # Export per-game results
    per_game_df.to_csv(f"{output_dir}/results_per_game.csv", index=False)
    per_game_df.to_json(f"{output_dir}/results_per_game.json", orient="records", indent=2)

    # Generate summary
    summary_lines = [
        "# Backtest Summary\n",
        f"Total games tested: {len(per_game_df)}\n",
    ]

    if not per_game_df.empty and "entry_price" in per_game_df.columns:
        summary_lines.append(
            f"Games with entry: {(per_game_df['entry_price'].notna()).sum()}\n"
        )
    if not per_game_df.empty and "settlement_occurred" in per_game_df.columns:
        summary_lines.append(
            f"Games settled: {(per_game_df['settlement_occurred'] == True).sum()}\n"
        )

    if not aggregated_df.empty and "net_roi_mean" in aggregated_df.columns:
        best_idx = aggregated_df["net_roi_mean"].idxmax()
        worst_idx = aggregated_df["net_roi_mean"].idxmin()

        if pd.notna(best_idx) and pd.notna(worst_idx):
            best_roi = aggregated_df.loc[best_idx]
            worst_roi = aggregated_df.loc[worst_idx]
            summary_lines.extend([
                f"\nBest performer (ROI): {best_roi['dip_threshold']}c dip, {best_roi['exit_type']} exit ({best_roi['net_roi_mean']:.2%})\n",
                f"Worst performer (ROI): {worst_roi['dip_threshold']}c dip, {worst_roi['exit_type']} exit ({worst_roi['net_roi_mean']:.2%})\n",
            ])

    with open(f"{output_dir}/BACKTEST_SUMMARY.txt", "w") as f:
        f.writelines(summary_lines)

    # Generate heatmap visualization
    if (
        not aggregated_df.empty
        and "dip_threshold" in aggregated_df.columns
        and "exit_type" in aggregated_df.columns
        and "net_roi_mean" in aggregated_df.columns
    ):
        try:
            pivoted = aggregated_df.pivot_table(
                index="exit_type",
                columns="dip_threshold",
                values="net_roi_mean",
                aggfunc="first",
            )

            if not pivoted.empty:
                fig = go.Figure(
                    data=go.Heatmap(
                        z=pivoted.values,
                        x=pivoted.columns,
                        y=pivoted.index,
                        colorscale="RdYlGn",
                    )
                )
                fig.update_layout(
                    title="Net ROI Heatmap by Dip Threshold and Exit Type",
                    xaxis_title="Dip Threshold (cents)",
                    yaxis_title="Exit Type",
                )
                fig.write_html(f"{output_dir}/roi_heatmap.html")
        except Exception:
            pass  # Skip heatmap if pivot fails

    # Generate schema documentation
    schema_lines = [
        "# Backtest Results Schema\n\n",
        "## Aggregated Results (results_aggregated.csv)\n",
        "- **dip_threshold**: Dip threshold in cents\n",
        "- **dip_anchor**: Price anchor for dip detection (open/tipoff)\n",
        "- **exit_type**: Exit strategy type\n",
        "- **fee_model**: Fee model (taker/maker)\n",
        "- **total_games**: Total games in universe for this combo\n",
        "- **games_with_entry**: Games where dip entry was triggered\n",
        "- **games_settled**: Games with event-derived settlement\n",
        "- **total_trades**: Total completed trades\n",
        "- **gross_roi_mean**: Mean ROI before fees\n",
        "- **net_roi_mean**: Mean ROI after fees\n",
        "- **win_rate**: Fraction of settled games that were profitable\n",
        "- **avg_entry_price**: Mean entry price\n",
        "- **avg_hold_minutes**: Mean hold duration\n",
        "\n## Per-Game Results (results_per_game.csv)\n",
        "- **match_id**: Match identifier\n",
        "- **date**: Game date (YYYY-MM-DD)\n",
        "- **sport**: Sport code (nba, nhl, mlb)\n",
        "- **entry_price**: Entry price (0-1 range)\n",
        "- **entry_time**: UTC timestamp of dip entry trade (ISO 8601)\n",
        "- **exit_price**: Exit price (or None if not triggered)\n",
        "- **gross_pnl_cents**: Gross profit/loss in cents\n",
        "- **net_pnl_cents**: Net PnL after fees\n",
        "- **roi_pct**: Return on investment percentage\n",
        "- **hold_seconds**: Hold duration in seconds\n",
        "- **settlement_method**: Event-derived or unresolved\n",
        "- **settlement_occurred**: True if game was settled\n",
        "- **true_pnl_cents**: PnL if held to settlement\n",
        "- **baseline_buy_at_open_roi**: Baseline ROI for buy-at-open\n",
        "- **baseline_buy_at_tip_roi**: Baseline ROI for buy-at-tipoff\n",
        "- **baseline_buy_first_ingame_roi**: Baseline ROI for buy-first-trade\n",
        "- **max_drawdown_cents**: Maximum adverse price move from entry (in cents)\n",
        "- **status**: Trade status (filled, not_triggered, etc.)\n",
    ]

    with open(f"{output_dir}/SCHEMA.md", "w") as f:
        f.writelines(schema_lines)
