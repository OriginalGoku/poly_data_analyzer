"""Tests for settlement resolution."""
import pandas as pd
import pytest

from backtest.backtest_settlement import resolve_settlement


@pytest.fixture
def nba_manifest():
    """NBA game manifest."""
    return {
        "match_id": "nba_game_1",
        "sport": "nba",
        "open_favorite_token": 0,  # Away team is favorite
    }


@pytest.fixture
def nba_events_away_wins():
    """NBA events with away team winning."""
    return pd.DataFrame(
        [
            {
                "time": "2026-03-23T19:30:00",
                "period": 1,
                "away_score": 10,
                "home_score": 8,
            },
            {
                "time": "2026-03-23T19:35:00",
                "period": 1,
                "away_score": 15,
                "home_score": 12,
            },
            {
                "time": "2026-03-23T20:30:00",
                "period": 4,
                "away_score": 105,
                "home_score": 102,
            },
        ]
    )


@pytest.fixture
def nba_events_home_wins():
    """NBA events with home team winning."""
    return pd.DataFrame(
        [
            {
                "time": "2026-03-23T19:30:00",
                "period": 1,
                "away_score": 10,
                "home_score": 15,
            },
            {
                "time": "2026-03-23T20:30:00",
                "period": 4,
                "away_score": 100,
                "home_score": 105,
            },
        ]
    )


def test_resolve_settlement_away_wins(nba_manifest, nba_events_away_wins):
    """Test settlement when away team (favorite) wins."""
    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=nba_events_away_wins,
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is True
    assert method == "event_derived"
    assert payout == 1.0  # Away team was favorite, and they won


def test_resolve_settlement_home_wins(nba_manifest, nba_events_home_wins):
    """Test settlement when home team wins against favorite."""
    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=nba_events_home_wins,
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is True
    assert method == "event_derived"
    assert payout == 0.0  # Away team was favorite, but home won


def test_resolve_settlement_no_events(nba_manifest):
    """Test settlement when no events are available."""
    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=pd.DataFrame(),
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is False
    assert method == "unresolved"
    assert payout is None


def test_resolve_settlement_none_events(nba_manifest):
    """Test settlement when events is None."""
    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=None,
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is False
    assert method == "unresolved"
    assert payout is None


def test_resolve_settlement_no_final_score(nba_manifest):
    """Test settlement when no final quarter events."""
    events = pd.DataFrame(
        [
            {
                "time": "2026-03-23T19:30:00",
                "period": 1,
                "away_score": 10,
                "home_score": 8,
            },
            {
                "time": "2026-03-23T19:35:00",
                "period": 2,
                "away_score": 20,
                "home_score": 18,
            },
        ]
    )

    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=events,
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is False
    assert method == "unresolved"


def test_resolve_settlement_home_favorite():
    """Test settlement when home team is favorite."""
    manifest = {
        "match_id": "nba_game_2",
        "sport": "nba",
        "open_favorite_token": 1,  # Home team is favorite
    }

    events = pd.DataFrame(
        [
            {
                "time": "2026-03-23T20:30:00",
                "period": 4,
                "away_score": 100,
                "home_score": 105,
            },
        ]
    )

    payout, method, settled = resolve_settlement(
        manifest=manifest,
        events=events,
        trades_df=None,
        game_end=None,
        sport="nba",
        settings=None,
    )

    assert settled is True
    assert payout == 1.0  # Home was favorite and won


def test_resolve_settlement_unsupported_sport(nba_manifest):
    """Test settlement for non-NBA sport (v1 unsupported)."""
    events = pd.DataFrame(
        [
            {
                "time": "2026-03-23T20:00:00",
                "period": 3,
            },
        ]
    )

    payout, method, settled = resolve_settlement(
        manifest=nba_manifest,
        events=events,
        trades_df=None,
        game_end=None,
        sport="nhl",  # Not NBA
        settings=None,
    )

    assert settled is False
    assert method == "unresolved"
