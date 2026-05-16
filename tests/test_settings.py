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


def test_roundtrip_via_load(tmp_path):
    cfg = tmp_path / "cs.json"
    cfg.write_text(json.dumps(ChartSettings(data_warning_min_pregame_vol=12345).to_dict()))
    loaded = load_chart_settings(cfg)
    assert loaded.data_warning_min_pregame_vol == 12345
