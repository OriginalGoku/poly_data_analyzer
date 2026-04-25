"""Tests for backtest.scenarios loader: sweep expansion, naming, validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.scenarios import load_scenarios


def _base_scenario(**overrides):
    raw = {
        "name": "demo",
        "universe_filter": {"name": "upper_strong", "params": {}},
        "side_target": "favorite",
        "trigger": {"name": "dip_below_anchor", "params": {"anchor": "open", "threshold_cents": 10}},
        "exit": {"name": "settlement", "params": {}},
        "lock": {"mode": "scale_in", "max_entries": 1, "cool_down_seconds": 0},
        "fee_model": "default",
    }
    raw.update(overrides)
    return raw


def _write(dir_path: Path, name: str, raw: dict) -> None:
    (dir_path / f"{name}.json").write_text(json.dumps(raw))


def test_dip_buy_favorite_expands_to_three_concrete_scenarios():
    scenarios = load_scenarios("backtest/scenarios")
    expected = {
        "dip_buy_favorite__trigger.params.threshold_cents=10",
        "dip_buy_favorite__trigger.params.threshold_cents=15",
        "dip_buy_favorite__trigger.params.threshold_cents=20",
    }
    assert expected.issubset(set(scenarios.keys()))
    for name in expected:
        s = scenarios[name]
        assert s.universe_filter.name == "upper_strong"
        assert s.side_target == "favorite"
        assert s.trigger.name == "dip_below_anchor"
        assert s.exit.name == "settlement"
        assert s.lock.mode == "scale_in"
        assert s.lock.max_entries == 5
        assert s.fee_model == "default"
    threshold_values = sorted(
        scenarios[n].trigger.params["threshold_cents"] for n in expected
    )
    assert threshold_values == [10, 15, 20]
    for n in expected:
        axes = scenarios[n].sweep_axes
        assert "trigger.params.threshold_cents" in axes


def test_empty_sweep_raises(tmp_path):
    raw = _base_scenario(name="empty")
    raw["trigger"]["params"]["threshold_cents"] = {"sweep": []}
    _write(tmp_path, "empty", raw)
    with pytest.raises(ValueError):
        load_scenarios(str(tmp_path))


def test_single_value_sweep_yields_one_scenario(tmp_path):
    raw = _base_scenario(name="single")
    raw["trigger"]["params"]["threshold_cents"] = {"sweep": [12]}
    _write(tmp_path, "single", raw)
    out = load_scenarios(str(tmp_path))
    assert list(out.keys()) == ["single__trigger.params.threshold_cents=12"]
    assert out[list(out.keys())[0]].trigger.params["threshold_cents"] == 12


def test_multi_axis_cartesian(tmp_path):
    raw = _base_scenario(name="multi")
    raw["trigger"]["params"]["threshold_cents"] = {"sweep": [10, 20]}
    raw["lock"]["max_entries"] = {"sweep": [1, 3]}
    _write(tmp_path, "multi", raw)
    out = load_scenarios(str(tmp_path))
    assert len(out) == 4
    for s in out.values():
        assert set(s.sweep_axes.keys()) == {
            "trigger.params.threshold_cents",
            "lock.max_entries",
        }


def test_duplicate_name_across_files_raises(tmp_path):
    raw1 = _base_scenario(name="dup")
    raw2 = _base_scenario(name="dup")
    _write(tmp_path, "a", raw1)
    _write(tmp_path, "b", raw2)
    with pytest.raises(ValueError, match="duplicate"):
        load_scenarios(str(tmp_path))


def test_bare_list_treated_as_literal(tmp_path):
    raw = _base_scenario(name="bare")
    raw["trigger"]["params"]["window_seconds_after_tipoff"] = [0, 3600]
    _write(tmp_path, "bare", raw)
    out = load_scenarios(str(tmp_path))
    assert list(out.keys()) == ["bare"]
    assert out["bare"].trigger.params["window_seconds_after_tipoff"] == [0, 3600]
    assert out["bare"].sweep_axes == {}


def test_favorite_drop_50pct_scenarios_parse_and_reference_live_components():
    import backtest.filters  # noqa: F401  (populate registries)
    import backtest.triggers  # noqa: F401
    import backtest.exits  # noqa: F401
    from backtest.registry import UNIVERSE_FILTERS, TRIGGERS, EXITS

    scenarios = load_scenarios("backtest/scenarios")

    bounded = scenarios["favorite_drop_50pct_60min_tp_sl"]
    assert bounded.universe_filter.name in UNIVERSE_FILTERS
    assert bounded.trigger.name in TRIGGERS
    assert bounded.exit.name in EXITS
    assert bounded.universe_filter.name == "first_k_above"
    assert bounded.trigger.name == "pct_drop_window"
    assert bounded.exit.name == "tp_sl"
    assert bounded.side_target == "favorite"
    assert bounded.trigger.params["window_seconds_after_tipoff"] == [0, 3600]
    assert bounded.exit.params["max_hold_seconds"] == 3600
    assert bounded.lock.mode == "scale_in"

    unbounded = scenarios["favorite_drop_50pct_unbounded_tp_sl"]
    assert unbounded.universe_filter.name in UNIVERSE_FILTERS
    assert unbounded.trigger.name in TRIGGERS
    assert unbounded.exit.name in EXITS
    assert unbounded.trigger.params["window_seconds_after_tipoff"] is None
    assert unbounded.exit.params["max_hold_seconds"] is None


def test_missing_required_key_raises(tmp_path):
    raw = _base_scenario(name="bad")
    del raw["fee_model"]
    _write(tmp_path, "bad", raw)
    with pytest.raises(ValueError, match="missing required key"):
        load_scenarios(str(tmp_path))
