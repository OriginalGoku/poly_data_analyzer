"""Game-level regime analytics for Polymarket sports markets."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
from functools import lru_cache
from pathlib import Path

import pandas as pd


BASE_RECORDS_CACHE_SCHEMA_VERSION = 1


def _base_records_settings_hash(
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
) -> str:
    payload = json.dumps(
        [float(pregame_min_cum_vol), str(open_anchor_stat), int(open_anchor_window_min)],
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def _base_records_file_fingerprint(path: Path) -> tuple[int | None, int | None]:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return (None, None)


def _base_records_input_fingerprint(data_dir: str, date: str, match_id: str) -> str:
    base = Path(data_dir) / date
    parts = (
        _base_records_file_fingerprint(base / f"{match_id}_trades.json.gz"),
        _base_records_file_fingerprint(base / "manifest.json"),
        _base_records_file_fingerprint(base / f"{match_id}_events.json.gz"),
    )
    return hashlib.sha1(json.dumps(parts).encode("utf-8")).hexdigest()


def _load_base_records_cache(cache_dir: Path, settings_hash: str) -> tuple[dict, dict]:
    """Return (records_by_key, fingerprint_map) from disk. Empty dicts on miss."""
    data_path = cache_dir / f"{settings_hash}.pkl"
    manifest_path = cache_dir / f"{settings_hash}.manifest.json"
    if not (data_path.exists() and manifest_path.exists()):
        return {}, {}
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        if manifest.get("schema_version") != BASE_RECORDS_CACHE_SCHEMA_VERSION:
            return {}, {}
        with open(data_path, "rb") as f:
            records_by_key: dict = pickle.load(f)
    except (OSError, pickle.UnpicklingError, json.JSONDecodeError):
        return {}, {}
    fingerprint_map = {tuple(k.split("|", 1)): v for k, v in manifest.get("input_fingerprint_map", {}).items()}
    return records_by_key, fingerprint_map


def _save_base_records_cache(
    cache_dir: Path,
    settings_hash: str,
    records_by_key: dict,
    fingerprint_map: dict,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_path = cache_dir / f"{settings_hash}.pkl"
    manifest_path = cache_dir / f"{settings_hash}.manifest.json"
    data_tmp = data_path.with_suffix(".pkl.tmp")
    manifest_tmp = manifest_path.with_suffix(".json.tmp")
    with open(data_tmp, "wb") as f:
        pickle.dump(records_by_key, f, protocol=pickle.HIGHEST_PROTOCOL)
    manifest_payload = {
        "schema_version": BASE_RECORDS_CACHE_SCHEMA_VERSION,
        "input_fingerprint_map": {f"{d}|{m}": fp for (d, m), fp in fingerprint_map.items()},
    }
    with open(manifest_tmp, "w") as f:
        json.dump(manifest_payload, f, indent=2)
    os.replace(data_tmp, data_path)
    os.replace(manifest_tmp, manifest_path)


INTERPRETABLE_BANDS = (
    ("Toss-Up", None, 0.50),
    ("Lean Favorite", 0.50, 0.53),
    ("Lower Moderate", 0.53, 0.65),
    ("Upper Moderate", 0.65, 0.77),
    ("Lower Strong", 0.77, 0.85),
    ("Upper Strong", 0.85, None),
)
INTERPRETABLE_BAND_LABELS = tuple(label for label, _, _ in INTERPRETABLE_BANDS)
ACTIVE_INTERPRETABLE_BAND_LABELS = tuple(
    label for label in INTERPRETABLE_BAND_LABELS if label != "Toss-Up"
)
QUANTILE_LABELS = ("Q1", "Q2", "Q3")
TIE_TOLERANCE = 1e-9


def get_available_sports(
    data_dir: str = "data",
    pregame_min_cum_vol: float = 0,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
) -> list[str]:
    """Return collected sports available in the local archive."""
    records = load_game_analytics(
        data_dir,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )
    if records.empty:
        return []
    return sorted(records["sport"].dropna().unique())


def get_analytics_view(
    data_dir: str = "data",
    sport: str | None = None,
    price_quality_filter: str = "all",
    pregame_min_cum_vol: float = 0,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    min_pregame_notional: float = 0,
) -> pd.DataFrame:
    """Return cached game analytics with quantile bands for the active filter."""
    records = load_game_analytics(
        data_dir,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )
    if records.empty:
        return records.copy()

    view = records.copy()
    if sport and sport != "all":
        view = view[view["sport"] == sport].copy()

    if start_date is not None:
        view = view[view["date"] >= start_date].copy()
    if end_date is not None:
        view = view[view["date"] <= end_date].copy()

    if min_pregame_notional > 0 and "pre_game_notional_usdc" in view.columns:
        view = view[view["pre_game_notional_usdc"].fillna(0) >= min_pregame_notional].copy()

    quantile_source = view
    if price_quality_filter != "all":
        quantile_source = quantile_source[
            quantile_source["price_quality"] == price_quality_filter
        ].copy()
        view = view[view["price_quality"] == price_quality_filter].copy()

    quantiles = _compute_quantile_thresholds(quantile_source)
    for anchor in ("open", "tipoff"):
        price_col = f"{anchor}_favorite_price"
        band_col = f"{anchor}_quantile_band"
        view[band_col] = view.apply(
            lambda row: _assign_quantile_band(
                row["sport"], row.get(price_col), quantiles.get((row["sport"], anchor))
            ),
            axis=1,
        )

    return view.sort_values(["date", "match_id"], ascending=[False, True]).reset_index(drop=True)


def load_game_analytics(
    data_dir: str = "data",
    pregame_min_cum_vol: float = 0,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Load and cache game-level checkpoint analytics for all collected markets.

    `start_date`/`end_date` are applied as a post-cache filter so the cached frame
    is repo-wide and reusable across date windows.
    """
    df = _load_game_analytics_cached(
        str(Path(data_dir).resolve()),
        float(pregame_min_cum_vol),
        str(open_anchor_stat),
        int(open_anchor_window_min),
    )
    if df.empty or (start_date is None and end_date is None):
        return df
    mask = pd.Series(True, index=df.index)
    if start_date is not None:
        mask &= df["date"] >= start_date
    if end_date is not None:
        mask &= df["date"] <= end_date
    return df[mask].copy()


@lru_cache(maxsize=2)
def _load_game_analytics_cached(
    data_dir: str,
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
) -> pd.DataFrame:
    return build_game_analytics_dataset(
        data_dir=data_dir,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
        start_date=None,
        end_date=None,
        progress_observer=None,
    )


def build_game_analytics_dataset(
    data_dir: str = "data",
    pregame_min_cum_vol: float = 0,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    progress_observer=None,
) -> pd.DataFrame:
    """Build uncached game analytics dataset with optional progress reporting."""
    base = Path(data_dir)
    records: list[dict] = []
    collected_jobs: list[tuple[str, dict, Path]] = []

    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        if not _date_in_range(date_dir.name, start_date, end_date):
            continue
        manifest_path = date_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        with open(manifest_path) as f:
            entries = json.load(f)

        for manifest in entries:
            if manifest.get("status") != "collected":
                continue
            trades_path = date_dir / f"{manifest['match_id']}_trades.json.gz"
            if not trades_path.exists():
                continue
            collected_jobs.append((date_dir.name, manifest, trades_path))

    if progress_observer is not None:
        progress_observer.start(
            total=len(collected_jobs),
            description="Building base analytics records",
        )

    for index, (date_name, manifest, trades_path) in enumerate(collected_jobs, start=1):
            trades_data = _read_trade_data(trades_path)
            records.append(
                _build_game_record(
                    date_name,
                    manifest,
                    trades_data,
                    pregame_min_cum_vol=pregame_min_cum_vol,
                    open_anchor_stat=open_anchor_stat,
                    open_anchor_window_min=open_anchor_window_min,
                )
            )
            if progress_observer is not None:
                progress_observer.advance(
                    index=index,
                    match_id=manifest["match_id"],
                    date=date_name,
                )

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for anchor in ("open", "tipoff"):
        price_col = f"{anchor}_favorite_price"
        band_col = f"{anchor}_interpretable_band"
        df[band_col] = df[price_col].apply(_assign_interpretable_band)
    if progress_observer is not None:
        progress_observer.finish(total=len(collected_jobs))
    return df


def stream_game_analytics(
    data_dir: str = "data",
    pregame_min_cum_vol: float = 0,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    progress_observer=None,
    base_records_cache_dir: str | Path | None = None,
):
    """Yield (base_record_dict, get_game) per collected game.

    `get_game` is a zero-arg callable that returns a `loaders.build_loaded_game`
    shaped dict. It is memoized — first call performs the read, subsequent calls
    return the cached value. When `base_records_cache_dir` is provided, the
    streaming helper consults the cached base-records frame and skips
    trades.json.gz reads for unchanged games (warm cross-restart path).
    """
    from loaders import build_loaded_game

    base = Path(data_dir)
    collected_jobs: list[tuple[str, dict, Path]] = []

    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        if not _date_in_range(date_dir.name, start_date, end_date):
            continue
        manifest_path = date_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        with open(manifest_path) as f:
            entries = json.load(f)
        for manifest in entries:
            if manifest.get("status") != "collected":
                continue
            trades_path = date_dir / f"{manifest['match_id']}_trades.json.gz"
            if not trades_path.exists():
                continue
            collected_jobs.append((date_dir.name, manifest, trades_path))

    base_cache: dict = {}
    base_fingerprints: dict = {}
    base_settings_hash = ""
    cache_dir_path = Path(base_records_cache_dir) if base_records_cache_dir else None
    if cache_dir_path is not None:
        base_settings_hash = _base_records_settings_hash(
            pregame_min_cum_vol, open_anchor_stat, open_anchor_window_min
        )
        base_cache, base_fingerprints = _load_base_records_cache(cache_dir_path, base_settings_hash)

    cache_dirty = False
    new_base_cache = dict(base_cache)
    new_fingerprints = dict(base_fingerprints)

    if progress_observer is not None:
        progress_observer.start(
            total=len(collected_jobs),
            description="Streaming game analytics",
        )

    def _make_lazy_loader(date_name, manifest, trades_path):
        cached = {"game": None, "trades_data": None}

        def _get_trades_data():
            if cached["trades_data"] is None:
                cached["trades_data"] = _read_trade_data(trades_path)
            return cached["trades_data"]

        def _get_game():
            if cached["game"] is None:
                cached["game"] = build_loaded_game(
                    data_dir, date_name, manifest, _get_trades_data()
                )
            return cached["game"]

        _get_game.get_trades_data = _get_trades_data  # type: ignore[attr-defined]
        return _get_game

    for index, (date_name, manifest, trades_path) in enumerate(collected_jobs, start=1):
        match_id = manifest["match_id"]
        key = (date_name, match_id)
        get_game = _make_lazy_loader(date_name, manifest, trades_path)

        record = None
        if cache_dir_path is not None:
            current_fp = _base_records_input_fingerprint(data_dir, date_name, match_id)
            if base_fingerprints.get(key) == current_fp and key in base_cache:
                record = dict(base_cache[key])
            else:
                trades_data = get_game.get_trades_data()  # type: ignore[attr-defined]
                record = _compute_base_record(
                    date_name,
                    manifest,
                    trades_data,
                    pregame_min_cum_vol,
                    open_anchor_stat,
                    open_anchor_window_min,
                )
                new_base_cache[key] = record
                new_fingerprints[key] = current_fp
                cache_dirty = True
        else:
            trades_data = get_game.get_trades_data()  # type: ignore[attr-defined]
            record = _compute_base_record(
                date_name,
                manifest,
                trades_data,
                pregame_min_cum_vol,
                open_anchor_stat,
                open_anchor_window_min,
            )

        yield record, get_game
        if progress_observer is not None:
            progress_observer.advance(
                index=index,
                match_id=match_id,
                date=date_name,
            )

    if cache_dir_path is not None and cache_dirty:
        # Drop entries for games no longer present.
        current_keys = {(d, m["match_id"]) for d, m, _ in collected_jobs}
        new_base_cache = {k: v for k, v in new_base_cache.items() if k in current_keys}
        new_fingerprints = {k: v for k, v in new_fingerprints.items() if k in current_keys}
        _save_base_records_cache(cache_dir_path, base_settings_hash, new_base_cache, new_fingerprints)

    if progress_observer is not None:
        progress_observer.finish(total=len(collected_jobs))


def _compute_base_record(
    date_name: str,
    manifest: dict,
    trades_data: dict,
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
) -> dict:
    record = _build_game_record(
        date_name,
        manifest,
        trades_data,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )
    record["date"] = pd.to_datetime(record["date"]).strftime("%Y-%m-%d")
    for anchor in ("open", "tipoff"):
        price = record.get(f"{anchor}_favorite_price")
        record[f"{anchor}_interpretable_band"] = _assign_interpretable_band(price)
    return record


def _date_in_range(date_name: str, start_date: str | None, end_date: str | None) -> bool:
    if not _looks_like_date(date_name):
        return False
    if start_date and date_name < start_date:
        return False
    if end_date and date_name > end_date:
        return False
    return True


def _looks_like_date(date_name: str) -> bool:
    try:
        pd.to_datetime(date_name, format="%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def _read_trade_data(path: Path) -> dict:
    """Read a trades file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _build_game_record(
    date: str,
    manifest: dict,
    trades_data: dict,
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
) -> dict:
    price_meta = trades_data.get("price_checkpoints_meta", {}) or {}
    checkpoints = trades_data.get("price_checkpoints", {}) or {}
    trades = trades_data.get("trades", []) or []

    open_snapshot = _meaningful_open_snapshot(
        manifest,
        trades,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )
    tipoff_snapshot = _favorite_snapshot(manifest, checkpoints, "last_pregame_trade_price")

    return {
        "date": date,
        "match_id": manifest["match_id"],
        "sport": manifest.get("sport"),
        "away_team": manifest.get("away_team"),
        "home_team": manifest.get("home_team"),
        "label": f"{manifest.get('away_team')} @ {manifest.get('home_team')}",
        "price_quality": price_meta.get("price_quality", "unknown"),
        "open_favorite_team": open_snapshot["team"],
        "open_favorite_price": open_snapshot["price"],
        "open_price_source": open_snapshot["source"],
        "tipoff_favorite_team": tipoff_snapshot["team"],
        "tipoff_favorite_price": tipoff_snapshot["price"],
        "tipoff_available": tipoff_snapshot["price"] is not None,
        "in_game_notional_usdc": manifest.get("volume_stats", {}).get("in_game_notional_usdc"),
        "pre_game_notional_usdc": manifest.get("volume_stats", {}).get("pre_game_notional_usdc"),
        "trade_count": manifest.get("volume_stats", {}).get("trade_count"),
    }


def _meaningful_open_snapshot(
    manifest: dict,
    trades: list[dict],
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
) -> dict:
    """Short post-threshold price window used as the market-open anchor."""
    if not trades:
        return {"team": None, "price": None, "source": None}

    gamma_start = _parse_iso(manifest.get("gamma_start_time"))
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return {"team": None, "price": None, "source": None}

    trades_df["datetime"] = pd.to_datetime(trades_df["timestamp"], unit="s", utc=True)
    pre_trades = trades_df
    if gamma_start is not None:
        pre_trades = pre_trades[pre_trades["datetime"] < gamma_start]

    pre_trades = _filter_by_min_cum_vol(pre_trades, pregame_min_cum_vol)
    if pre_trades.empty:
        return {"team": None, "price": None, "source": None}

    threshold_time = pre_trades["datetime"].min()
    window_end = threshold_time + pd.Timedelta(minutes=open_anchor_window_min)
    window_trades = pre_trades[pre_trades["datetime"] <= window_end]

    prices: dict[str, float] = {}
    used_fallback = False
    for token_id, team in zip(manifest.get("token_ids", []), manifest.get("outcomes", [])):
        token_trades = window_trades[window_trades["asset"] == token_id]
        if token_trades.empty:
            token_trades = pre_trades[pre_trades["asset"] == token_id]
            used_fallback = True
        if token_trades.empty:
            continue
        prices[team] = _aggregate_anchor_price(token_trades, open_anchor_stat)

    if not prices:
        return {"team": None, "price": None, "source": None}

    favorite_team, favorite_price = _pick_favorite(prices)
    source = f"post_min_cum_vol_{open_anchor_stat}_{open_anchor_window_min}m"
    if used_fallback:
        source = f"{source}_fallback"
    return {
        "team": favorite_team,
        "price": favorite_price,
        "source": source,
    }


def _aggregate_anchor_price(trades_df: pd.DataFrame, open_anchor_stat: str) -> float:
    clean = trades_df.dropna(subset=["price"])
    if clean.empty:
        return None
    if open_anchor_stat == "median":
        return float(clean["price"].median())

    weights = clean["size"].fillna(0).astype(float)
    prices = clean["price"].astype(float)
    if (weights > 0).any():
        return float((prices * weights).sum() / weights.sum())
    return float(prices.mean())


def _favorite_snapshot(manifest: dict, checkpoints: dict, field: str) -> dict:
    prices: dict[str, float] = {}
    source = None
    for token_id, team in zip(manifest.get("token_ids", []), manifest.get("outcomes", [])):
        cp = checkpoints.get(token_id, {}) or {}
        price = cp.get(field)
        if price is None:
            continue
        prices[team] = float(price)
        if field == "selected_early_price":
            source = cp.get("selected_early_price_source")

    if not prices:
        return {"team": None, "price": None, "source": None}

    favorite_team, favorite_price = _pick_favorite(prices)
    return {
        "team": favorite_team,
        "price": favorite_price,
        "source": source if field == "selected_early_price" else "last_pregame_trade",
    }


def _pick_favorite(prices: dict[str, float]) -> tuple[str, float]:
    """Pick the favorite team from team->price, returning Tie when equal."""
    ordered = sorted(prices.items(), key=lambda item: item[1], reverse=True)
    top_team, top_price = ordered[0]
    if len(ordered) > 1 and abs(top_price - ordered[1][1]) <= TIE_TOLERANCE:
        return "Tie", top_price
    return top_team, top_price


def _filter_by_min_cum_vol(trades_df: pd.DataFrame, min_vol: float) -> pd.DataFrame:
    """Drop trades before cumulative volume first reaches min_vol."""
    if trades_df.empty or min_vol <= 0:
        return trades_df.sort_values("datetime")
    sorted_df = trades_df.sort_values("datetime")
    cum = sorted_df["size"].cumsum()
    mask = cum >= min_vol
    if not mask.any():
        return sorted_df
    return sorted_df.loc[mask]


def _parse_iso(s: str | None):
    """Parse ISO timestamp string to timezone-aware datetime, or None."""
    if not s:
        return None
    return pd.to_datetime(s, utc=True)


def _assign_interpretable_band(price: float | None) -> str | None:
    if price is None or pd.isna(price):
        return None
    for label, lower, upper in INTERPRETABLE_BANDS:
        if upper is None and price >= lower:
            return label
        if lower is not None and upper is not None and lower <= price < upper:
            return label
    return None


def _compute_quantile_thresholds(df: pd.DataFrame) -> dict[tuple[str, str], tuple[float, float]]:
    thresholds: dict[tuple[str, str], tuple[float, float]] = {}
    if df.empty:
        return thresholds

    for sport in sorted(df["sport"].dropna().unique()):
        sport_df = df[df["sport"] == sport]
        for anchor in ("open", "tipoff"):
            prices = (
                sport_df[f"{anchor}_favorite_price"]
                .dropna()
                .astype(float)
            )
            if prices.empty:
                continue
            q1 = float(prices.quantile(1 / 3))
            q2 = float(prices.quantile(2 / 3))
            thresholds[(sport, anchor)] = (q1, q2)
    return thresholds


def _assign_quantile_band(
    sport: str,
    price: float | None,
    thresholds: tuple[float, float] | None,
) -> str | None:
    if price is None or pd.isna(price) or thresholds is None:
        return None
    q1, q2 = thresholds
    if price < q1:
        return QUANTILE_LABELS[0]
    if price < q2:
        return QUANTILE_LABELS[1]
    return QUANTILE_LABELS[2]


def build_analysis_summary(game_row: pd.Series, population: pd.DataFrame) -> dict:
    """Build a UI-ready summary for a selected game and its comparison set."""
    thresholds = _compute_quantile_thresholds(population)
    sport = game_row["sport"]

    open_cutoffs = thresholds.get((sport, "open"))
    tipoff_cutoffs = thresholds.get((sport, "tipoff"))

    return {
        "sport": sport,
        "price_quality": game_row["price_quality"],
        "population_games": len(population),
        "open": {
            "team": game_row["open_favorite_team"],
            "price": game_row["open_favorite_price"],
            "source": game_row["open_price_source"],
            "interpretable_band": game_row["open_interpretable_band"],
            "quantile_band": game_row["open_quantile_band"],
            "quantile_cutoffs": open_cutoffs,
        },
        "tipoff": {
            "team": game_row["tipoff_favorite_team"],
            "price": game_row["tipoff_favorite_price"],
            "source": "last_pregame_trade" if game_row["tipoff_available"] else None,
            "interpretable_band": game_row["tipoff_interpretable_band"],
            "quantile_band": game_row["tipoff_quantile_band"],
            "quantile_cutoffs": tipoff_cutoffs,
        },
    }
