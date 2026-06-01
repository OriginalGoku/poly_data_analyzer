"""Run the underdog TP×SL bracket edge test on NHL and MLB (and NBA for parity).

Reuses the validated first-passage + walk-forward + bootstrap machinery. Bands
are price-based, so "Lean Favorite" (favorite 0.50-0.53) is defined identically
across sports. Streams each sport once.

Usage: python scripts/cross_sport_edge_check.py [nhl mlb nba]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics import _assign_interpretable_band, stream_game_analytics
from loaders import _derive_nba_final_winner
from nba_analysis import _compute_tipoff_entry_window_price, _resolve_score_tipoff_time
from nba_tipoff_bracket import _favorite_ingame_prices
from nba_tipoff_bracket_validation import bootstrap_bracket_ci, walk_forward_bracket
from settings import load_chart_settings


def collect_sport_paths(sport: str, settings, data_dir: str = "data"):
    """Build [(band, date, favorite_won, favorite_entry, fav_price_path), ...] for one sport."""
    paths = []
    n_seen = 0
    for base, get_game in stream_game_analytics(
        data_dir=data_dir,
        pregame_min_cum_vol=float(getattr(settings, "pregame_min_cum_vol", 0)),
        base_records_cache_dir="cache/_base_records",
    ):
        if base.get("sport") != sport:
            continue
        n_seen += 1
        fav_team = base.get("tipoff_favorite_team")
        fav_price = base.get("tipoff_favorite_price")
        if not fav_team or fav_price is None:
            continue
        band = _assign_interpretable_band(fav_price)
        if band is None:
            continue
        try:
            game = get_game()
            winner = _derive_nba_final_winner(game["manifest"], game["events"])
            if winner is None:
                continue
            won = winner == fav_team
            tip_time = _resolve_score_tipoff_time(game["events"])
            entry, _ = _compute_tipoff_entry_window_price(
                game["trades_df"], game["manifest"], fav_team, tip_time,
                int(getattr(settings, "tipoff_entry_window_trades", 30)),
            )
            if entry is None:
                continue
            prices = _favorite_ingame_prices(
                game["trades_df"], game["events"], game["manifest"], settings, fav_team
            )
        except Exception:
            continue
        paths.append((band, base["date"], won, float(entry), prices))
    return paths, n_seen


def main(sports):
    settings = load_chart_settings("chart_settings.json")
    fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0
    slip = float(getattr(settings, "stop_loss_slippage_bps", 0.0)) / 10000.0
    for sport in sports:
        paths, n_seen = collect_sport_paths(sport, settings)
        print(f"\n############ {sport.upper()} — {len(paths)} usable / {n_seen} streamed ############")
        for side in ("underdog", "favorite"):
            wf = walk_forward_bracket(paths, side, fee, slip, n_folds=5)
            boot = bootstrap_bracket_ci(paths, side, fee, slip, n_boot=5000, seed=0)
            print(f"\n=== {sport.upper()} {side.upper()} — WALK-FORWARD ===")
            print(wf.to_string(index=False) if not wf.empty else "empty")
            print(f"\n=== {sport.upper()} {side.upper()} — BOOTSTRAP CI @ argmax bracket ===")
            print(boot.to_string(index=False) if not boot.empty else "empty")
    print("\nDONE")


if __name__ == "__main__":
    main(sys.argv[1:] or ["nhl", "mlb"])
