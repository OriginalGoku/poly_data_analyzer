"""Whale wallet analysis for Polymarket NBA trade data."""

import pandas as pd


def analyze_whales(trades_df: pd.DataFrame, settings: dict | None = None) -> dict:
    """Identify and classify whale wallets from trade data.

    Returns dict with keys:
        whales: list of whale dicts sorted by total_volume desc
        summary: dict with whale_count, whale_volume, whale_pct, total_volume
    """
    settings = settings or {}
    min_pct = settings.get("whale_min_volume_pct", 2.0)
    max_count = settings.get("whale_max_count", 10)
    maker_threshold = settings.get("whale_maker_threshold_pct", 60)

    if trades_df.empty:
        return {"whales": [], "summary": {
            "whale_count": 0, "whale_volume": 0, "whale_pct": 0, "total_volume": 0,
        }}

    total_volume = trades_df["size"].sum()

    # Collect all unique wallet addresses from maker and taker columns
    wallets = set(trades_df["maker"].dropna().unique()) | set(trades_df["taker"].dropna().unique())

    wallet_stats = []
    for addr in wallets:
        maker_trades = trades_df[trades_df["maker"] == addr]
        taker_trades = trades_df[trades_df["taker"] == addr]

        maker_volume = maker_trades["size"].sum()
        taker_volume = taker_trades["size"].sum()
        total_vol = maker_volume + taker_volume
        trade_count = len(maker_trades) + len(taker_trades)

        pct_of_total = total_vol / total_volume * 100 if total_volume > 0 else 0

        # Side attribution from taker trades only
        buy_volume = taker_trades[taker_trades["side"] == "BUY"]["size"].sum()
        sell_volume = taker_trades[taker_trades["side"] == "SELL"]["size"].sum()
        teams_traded = set(taker_trades["team"].dropna().unique())

        # Primary side (taker trades only)
        taker_total = buy_volume + sell_volume
        if taker_total > 0:
            if buy_volume / taker_total > 0.65:
                primary_side = "BUY"
            elif sell_volume / taker_total > 0.65:
                primary_side = "SELL"
            else:
                primary_side = "Mixed"
        else:
            primary_side = "N/A"

        # Classification
        maker_pct = maker_volume / total_vol * 100 if total_vol > 0 else 0
        taker_pct = taker_volume / total_vol * 100 if total_vol > 0 else 0

        if maker_pct >= maker_threshold and trade_count >= 20:
            classification = "Market Maker"
        elif taker_pct >= maker_threshold:
            classification = "Directional"
        else:
            classification = "Hybrid"

        display_addr = f"0x{addr[2:6]}...{addr[-4:]}"

        wallet_stats.append({
            "address": addr,
            "display_addr": display_addr,
            "maker_volume": maker_volume,
            "taker_volume": taker_volume,
            "total_volume": total_vol,
            "trade_count": trade_count,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "teams_traded": teams_traded,
            "pct_of_total": pct_of_total,
            "primary_side": primary_side,
            "classification": classification,
            "maker_pct": maker_pct,
            "taker_pct": taker_pct,
        })

    # Filter by min pct, sort by total volume, cap at max count
    whales = [w for w in wallet_stats if w["pct_of_total"] >= min_pct]
    whales.sort(key=lambda w: w["total_volume"], reverse=True)
    whales = whales[:max_count]

    whale_volume = sum(w["total_volume"] for w in whales)
    whale_pct = whale_volume / total_volume * 100 if total_volume > 0 else 0

    return {
        "whales": whales,
        "summary": {
            "whale_count": len(whales),
            "whale_volume": whale_volume,
            "whale_pct": whale_pct,
            "total_volume": total_volume,
        },
    }


def get_whale_trades(trades_df: pd.DataFrame, whale_addresses: set[str]) -> pd.DataFrame:
    """Filter trades to only those involving a whale as maker or taker."""
    if trades_df.empty or not whale_addresses:
        return trades_df.iloc[0:0]  # empty with same columns
    mask = trades_df["maker"].isin(whale_addresses) | trades_df["taker"].isin(whale_addresses)
    return trades_df[mask]
