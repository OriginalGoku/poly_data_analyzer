"""Tests for the band_drop_recovery_sweep scenario file."""
from __future__ import annotations

from backtest.scenarios import load_scenarios


EXPECTED_DROPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]


def test_band_drop_recovery_sweep_expands_to_ten_scenarios():
    import backtest.filters  # noqa: F401  (populate registries)
    import backtest.triggers  # noqa: F401
    import backtest.exits  # noqa: F401
    from backtest.registry import UNIVERSE_FILTERS, TRIGGERS, EXITS

    scenarios = load_scenarios("backtest/scenarios")

    expected_names = {
        f"band_drop_recovery_sweep__trigger.params.drop_pct={d}"
        for d in EXPECTED_DROPS
    }
    assert expected_names.issubset(set(scenarios.keys()))

    drops = sorted(
        scenarios[n].trigger.params["drop_pct"] for n in expected_names
    )
    assert drops == EXPECTED_DROPS

    for name in expected_names:
        s = scenarios[name]
        assert s.universe_filter.name == "first_k_above"
        assert s.universe_filter.name in UNIVERSE_FILTERS
        assert s.universe_filter.params["k"] == 1
        assert s.universe_filter.params["min_price"] == 0.50
        assert s.universe_filter.params["exclude_inferred_price_quality"] is False
        assert s.side_target == "favorite"
        assert s.trigger.name == "pct_drop_window"
        assert s.trigger.name in TRIGGERS
        assert s.trigger.params["anchor"] == "tipoff"
        assert s.trigger.params["window_seconds_after_tipoff"] is None
        assert s.exit.name == "reversion_to_open"
        assert s.exit.name in EXITS
        assert s.exit.params == {}
        assert s.lock.mode == "sequential"
        assert s.lock.max_entries == 1
        assert s.lock.cool_down_seconds == 0
        assert s.lock.allow_re_arm_after_stop_loss is False
        assert s.fee_model == "taker"
        assert "trigger.params.drop_pct" in s.sweep_axes
