"""Live win-probability model for NBA favorites (Lever 3).

Builds an empirical ``P(favorite wins | game-time bucket, favorite-lead bucket)``
table from historical score events, then tests whether the market price
*deviating* from that model predicts returns — i.e. whether mispricing vs the
live game state is tradeable, rather than relying on entry/exit rules alone.

Honesty: the win-prob table is fit on a chronological **train** slice and the
mispricing edge is measured on a held-out **test** slice (no in-sample leakage).

The tradeable claim under test: "buy the favorite when the model says it is
underpriced (model_prob - market_price >= edge)" and hold to settlement →
EV per unit stake = realized_win_rate - mean_market_price - fee.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import stream_game_analytics

# NBA regulation = 48 min; last bucket absorbs OT.
TIME_BUCKETS = [(0, 12), (12, 24), (24, 36), (36, 48), (48, 200)]
LEAD_EDGES = [-100, -15, -8, -3, 3, 8, 15, 100]
EDGE_BUCKETS = [(-1.0, -0.10), (-0.10, -0.05), (-0.05, 0.05), (0.05, 0.10), (0.10, 1.0)]

WIN_PROB_TABLE_COLUMNS = ("time_bucket", "lead_bucket", "n", "win_rate")
MISPRICING_COLUMNS = (
    "edge_bucket",
    "n",
    "realized_win_rate",
    "mean_market_price",
    "ev_per_unit_stake",
    "mean_model_prob",
)


def _time_bucket(minutes: float) -> str:
    for lo, hi in TIME_BUCKETS:
        if lo <= minutes < hi:
            return f"{lo}-{hi}m"
    return f"{TIME_BUCKETS[-1][0]}-{TIME_BUCKETS[-1][1]}m"


def _lead_bucket(lead: int) -> str:
    for i in range(len(LEAD_EDGES) - 1):
        lo, hi = LEAD_EDGES[i], LEAD_EDGES[i + 1]
        if lo <= lead < hi:
            return f"[{lo},{hi})"
    return f"[{LEAD_EDGES[-2]},{LEAD_EDGES[-1]})"


def _edge_bucket(edge: float) -> str:
    for lo, hi in EDGE_BUCKETS:
        if lo <= edge < hi:
            return f"[{lo:+.2f},{hi:+.2f})"
    return f"[{EDGE_BUCKETS[-1][0]:+.2f},{EDGE_BUCKETS[-1][1]:+.2f})"


def _favorite_price_series(trades_df: pd.DataFrame, manifest: dict, fav_team: str):
    """(sorted datetime64[ns] array, favorite-side price array) for asof lookups."""
    if (
        trades_df.empty
        or len(manifest.get("token_ids", [])) < 2
        or len(manifest.get("outcomes", [])) < 2
    ):
        return np.array([], dtype="datetime64[ns]"), np.array([], dtype=float)
    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    if fav_team not in (away_team, home_team):
        return np.array([], dtype="datetime64[ns]"), np.array([], dtype=float)

    sdf = trades_df.sort_values("datetime")
    away_price = sdf["price"].astype(float).to_numpy().copy()
    home_mask = (sdf["asset"] != away_token).to_numpy()
    away_price[home_mask] = 1.0 - away_price[home_mask]
    fav_price = away_price if fav_team == away_team else 1.0 - away_price
    times = sdf["datetime"].to_numpy(dtype="datetime64[ns]")
    return times, fav_price


def _price_asof(times: np.ndarray, prices: np.ndarray, t) -> float | None:
    """Last favorite-side price at or before time ``t`` (None if none yet).

    ``times`` and ``t`` are compared as ``datetime64[ns]`` to avoid time-unit
    mismatches (trade timestamps may be us- or ns-resolution).
    """
    if times.size == 0:
        return None
    key = np.datetime64(pd.Timestamp(t), "ns")
    idx = int(np.searchsorted(times, key, side="right")) - 1
    if idx < 0:
        return None
    return float(prices[idx])


def extract_game_samples(
    events: list[dict] | None,
    trades_df: pd.DataFrame,
    manifest: dict,
    fav_team: str,
    won: bool,
    date: str,
    match_id: str,
) -> list[dict]:
    """One row per score event after tip-off: (time, lead, market_price, won)."""
    if not events or fav_team is None:
        return []
    score_events = [
        e
        for e in events
        if e.get("time_actual_dt") is not None
        and e.get("away_score") is not None
        and e.get("home_score") is not None
    ]
    if not score_events:
        return []
    away_team = manifest.get("outcomes", [None, None])[0]
    fav_is_away = fav_team == away_team

    tipoff_time = min(e["time_actual_dt"] for e in score_events)
    times, prices = _favorite_price_series(trades_df, manifest, fav_team)

    out = []
    for e in score_events:
        t = e["time_actual_dt"]
        elapsed_min = (t - tipoff_time).total_seconds() / 60.0
        if elapsed_min < 0:
            continue
        lead = (
            int(e["away_score"]) - int(e["home_score"])
            if fav_is_away
            else int(e["home_score"]) - int(e["away_score"])
        )
        market_price = _price_asof(times, prices, t)
        if market_price is None:
            continue
        out.append(
            {
                "date": date,
                "match_id": match_id,
                "elapsed_min": elapsed_min,
                "time_bucket": _time_bucket(elapsed_min),
                "lead": lead,
                "lead_bucket": _lead_bucket(lead),
                "market_price": market_price,
                "won": bool(won),
            }
        )
    return out


def build_win_prob_table(samples: pd.DataFrame) -> pd.DataFrame:
    """Empirical P(win | time_bucket, lead_bucket)."""
    cols = list(WIN_PROB_TABLE_COLUMNS)
    if samples.empty:
        return pd.DataFrame(columns=cols)
    g = samples.groupby(["time_bucket", "lead_bucket"])
    table = g.agg(n=("won", "size"), win_rate=("won", "mean")).reset_index()
    return table[cols]


def evaluate_mispricing(samples: pd.DataFrame, table: pd.DataFrame, fee: float = 0.0) -> pd.DataFrame:
    """Bucket test samples by model-vs-market edge; report realized EV of buying."""
    cols = list(MISPRICING_COLUMNS)
    if samples.empty or table.empty:
        return pd.DataFrame(columns=cols)
    lookup = {
        (r["time_bucket"], r["lead_bucket"]): r["win_rate"] for _, r in table.iterrows()
    }
    df = samples.copy()
    df["model_prob"] = df.apply(
        lambda r: lookup.get((r["time_bucket"], r["lead_bucket"])), axis=1
    )
    df = df[df["model_prob"].notna()]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["edge"] = df["model_prob"] - df["market_price"]
    df["edge_bucket"] = df["edge"].apply(_edge_bucket)

    rows = []
    order = [f"[{lo:+.2f},{hi:+.2f})" for lo, hi in EDGE_BUCKETS]
    for bucket, grp in df.groupby("edge_bucket"):
        win_rate = float(grp["won"].mean())
        mean_price = float(grp["market_price"].mean())
        rows.append(
            {
                "edge_bucket": bucket,
                "n": int(len(grp)),
                "realized_win_rate": win_rate,
                "mean_market_price": mean_price,
                "ev_per_unit_stake": win_rate - mean_price - fee,
                "mean_model_prob": float(grp["model_prob"].mean()),
            }
        )
    result = pd.DataFrame(rows, columns=cols)
    present = [b for b in order if b in set(result["edge_bucket"])]
    if present:
        result["edge_bucket"] = pd.Categorical(result["edge_bucket"], categories=present, ordered=True)
        result = result.sort_values("edge_bucket").reset_index(drop=True)
        result["edge_bucket"] = result["edge_bucket"].astype(str)
    return result


def build_winprob_analysis(
    data_dir: str,
    settings,
    dataset: pd.DataFrame,
    train_frac: float = 0.7,
    base_records_cache_dir=None,
):
    """Stream games once; build a train win-prob table + test mispricing EV.

    Returns ``(win_prob_table, mispricing_test, n_train_games, n_test_games)``.
    """
    empty = (
        pd.DataFrame(columns=list(WIN_PROB_TABLE_COLUMNS)),
        pd.DataFrame(columns=list(MISPRICING_COLUMNS)),
        0,
        0,
    )
    required = {"date", "match_id", "tipoff_favorite_won", "tipoff_favorite_team", "sport"}
    if dataset.empty or not required.issubset(dataset.columns):
        return empty

    valid = dataset[
        (dataset["sport"] == "nba")
        & dataset["tipoff_favorite_won"].notna()
        & dataset["tipoff_favorite_team"].notna()
    ]
    if valid.empty:
        return empty
    lookup = {
        (r["date"], r["match_id"]): (bool(r["tipoff_favorite_won"]), r["tipoff_favorite_team"])
        for _, r in valid.iterrows()
    }

    fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0

    all_samples: list[dict] = []
    for base_record, get_game in stream_game_analytics(
        data_dir=data_dir,
        pregame_min_cum_vol=float(getattr(settings, "pregame_min_cum_vol", 0)),
        base_records_cache_dir=str(base_records_cache_dir) if base_records_cache_dir else None,
    ):
        key = (base_record.get("date"), base_record.get("match_id"))
        if key not in lookup:
            continue
        won, fav_team = lookup[key]
        game = get_game()
        all_samples.extend(
            extract_game_samples(
                game["events"], game["trades_df"], game["manifest"],
                fav_team, won, key[0], key[1],
            )
        )

    if not all_samples:
        return empty
    samples = pd.DataFrame(all_samples)

    # Chronological split by date.
    dates = sorted(samples["date"].unique())
    cut = int(len(dates) * train_frac)
    if cut <= 0 or cut >= len(dates):
        return empty
    cutoff = dates[cut]
    train = samples[samples["date"] < cutoff]
    test = samples[samples["date"] >= cutoff]
    if train.empty or test.empty:
        return empty

    table = build_win_prob_table(train)
    mispricing = evaluate_mispricing(test, table, fee=fee)
    return (
        table,
        mispricing,
        int(train["match_id"].nunique()),
        int(test["match_id"].nunique()),
    )
