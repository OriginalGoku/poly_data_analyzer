"""Direct unit tests for loaders.build_loaded_game.

Covered transitively via load_game elsewhere; these tests pin its contract
as a standalone helper used by streaming pipelines.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loaders import build_loaded_game


def _write_events(path: Path, events: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"events": events}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)


@pytest.fixture
def manifest():
    return {
        "match_id": "nba-1",
        "sport": "nba",
        "status": "collected",
        "away_team": "Brooklyn Nets",
        "home_team": "Orlando Magic",
        "outcomes": ["Brooklyn Nets", "Orlando Magic"],
        "token_ids": ["tok-a", "tok-h"],
        "gamma_start_time": "2026-04-10T19:00:00Z",
        "gamma_closed_time": "2026-04-10T22:00:00Z",
    }


def test_returns_expected_shape_without_events(tmp_path, manifest):
    trades_data = {
        "price_checkpoints_meta": {"price_quality": "exact"},
        "trades": [
            {"timestamp": 1_700_000_000, "asset": "tok-a", "price": 0.4, "size": 100},
            {"timestamp": 1_700_000_001, "asset": "tok-h", "price": 0.6, "size": 200},
        ],
    }
    out = build_loaded_game(str(tmp_path), "2026-04-10", manifest, trades_data)

    assert set(out.keys()) == {
        "manifest", "trades_df", "trades_meta",
        "events", "tricode_map", "gamma_start", "gamma_closed",
    }
    assert out["manifest"] is manifest
    assert out["events"] is None
    assert out["tricode_map"] == {}
    assert out["gamma_start"].isoformat() == "2026-04-10T19:00:00+00:00"
    assert out["gamma_closed"].isoformat() == "2026-04-10T22:00:00+00:00"
    # trades_meta excludes "trades" key
    assert "trades" not in out["trades_meta"]
    assert out["trades_meta"]["price_checkpoints_meta"]["price_quality"] == "exact"
    # team mapping applied from token_ids/outcomes
    teams = set(out["trades_df"]["team"])
    assert teams == {"Brooklyn Nets", "Orlando Magic"}
    # datetime column present and UTC
    assert pd.api.types.is_datetime64_any_dtype(out["trades_df"]["datetime"])


def test_loads_events_and_builds_tricode_map(tmp_path, manifest):
    base = tmp_path / "2026-04-10"
    events = [
        {
            "team_tricode": "BKN",
            "away_score": 2,
            "home_score": 0,
            "time_actual": "2026-04-10T19:01:00Z",
        },
        {
            "team_tricode": "ORL",
            "away_score": 2,
            "home_score": 3,
            "time_actual": "2026-04-10T19:02:00Z",
        },
    ]
    _write_events(base / "nba-1_events.json.gz", events)

    trades_data = {
        "trades": [{"timestamp": 1_700_000_000, "asset": "tok-a", "price": 0.5, "size": 10}],
    }
    out = build_loaded_game(str(tmp_path), "2026-04-10", manifest, trades_data)

    assert out["events"] is not None
    assert len(out["events"]) == 2
    # time_actual_dt added to each event
    assert out["events"][0]["time_actual_dt"] is not None
    assert out["tricode_map"] == {"BKN": "Brooklyn Nets", "ORL": "Orlando Magic"}


def test_outlier_settings_passed_through(tmp_path, manifest):
    """When outlier filtering is disabled (windows=0), no rows are dropped."""
    trades_data = {
        "trades": [
            {"timestamp": 1_700_000_000, "asset": "tok-a", "price": 0.40, "size": 100},
            # An extreme outlier that would be filtered with defaults
            {"timestamp": 1_700_000_001, "asset": "tok-a", "price": 0.01, "size": 100},
            {"timestamp": 1_700_000_002, "asset": "tok-a", "price": 0.41, "size": 100},
            {"timestamp": 1_700_000_003, "asset": "tok-a", "price": 0.42, "size": 100},
        ],
    }
    out = build_loaded_game(
        str(tmp_path), "2026-04-10", manifest, trades_data,
        outlier_settings={"outlier_backward_window": 0, "outlier_forward_window": 0},
    )
    assert len(out["trades_df"]) == 4
