"""Tests for ChartSettings dataclass."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settings import ChartSettings, load_chart_settings


def test_default_data_warning_min_pregame_vol():
    assert ChartSettings().data_warning_min_pregame_vol == 20000


def test_to_dict_includes_new_field():
    d = ChartSettings().to_dict()
    assert d["data_warning_min_pregame_vol"] == 20000
    assert d["pregame_min_cum_vol"] == 5000


def test_default_max_favorite_price_threshold():
    assert ChartSettings().max_favorite_price_threshold == 0.97


def test_to_dict_includes_max_favorite_price_threshold():
    d = ChartSettings().to_dict()
    assert d["max_favorite_price_threshold"] == 0.97


def test_max_favorite_price_threshold_roundtrip(tmp_path):
    cfg = tmp_path / "cs.json"
    cfg.write_text(json.dumps(ChartSettings(max_favorite_price_threshold=0.85).to_dict()))
    loaded = load_chart_settings(cfg)
    assert loaded.max_favorite_price_threshold == 0.85


def test_roundtrip_via_load(tmp_path):
    cfg = tmp_path / "cs.json"
    cfg.write_text(json.dumps(ChartSettings(data_warning_min_pregame_vol=12345).to_dict()))
    loaded = load_chart_settings(cfg)
    assert loaded.data_warning_min_pregame_vol == 12345


def test_stop_loss_settings_defaults():
    s = ChartSettings()
    assert s.tipoff_entry_window_trades == 30
    assert s.stop_loss_fee_bps == 0.0
    assert s.stop_loss_slippage_bps == 0.0


def test_stop_loss_settings_roundtrip(tmp_path):
    cfg = tmp_path / "cs.json"
    cfg.write_text(
        json.dumps(
            ChartSettings(
                tipoff_entry_window_trades=15,
                stop_loss_fee_bps=12.5,
                stop_loss_slippage_bps=3.0,
            ).to_dict()
        )
    )
    loaded = load_chart_settings(cfg)
    assert loaded.tipoff_entry_window_trades == 15
    assert loaded.stop_loss_fee_bps == 12.5
    assert loaded.stop_loss_slippage_bps == 3.0
