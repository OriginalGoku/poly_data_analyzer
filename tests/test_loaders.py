"""Tests for pure helper functions in loaders.py."""

from datetime import datetime, timezone

import pytest

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loaders import (
    _build_tricode_map,
    _derive_nba_final_score,
    _derive_nba_final_winner,
    _is_date_dir,
    _parse_iso,
)


# --- _is_date_dir ---

class TestIsDateDir:
    def test_valid_date(self):
        assert _is_date_dir("2025-11-14") is True

    def test_valid_date_different_month(self):
        assert _is_date_dir("2024-01-01") is True

    def test_invalid_format_slash(self):
        assert _is_date_dir("2025/11/14") is False

    def test_invalid_not_a_date(self):
        assert _is_date_dir("not-a-date") is False

    def test_invalid_empty_string(self):
        assert _is_date_dir("") is False

    def test_invalid_partial_date(self):
        assert _is_date_dir("2025-11") is False

    def test_invalid_month_13(self):
        assert _is_date_dir("2025-13-01") is False


# --- _parse_iso ---

class TestParseIso:
    def test_parse_z_suffix(self):
        result = _parse_iso("2025-11-14T20:00:00Z")
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2025
        assert result.month == 11
        assert result.day == 14

    def test_parse_offset_suffix(self):
        result = _parse_iso("2025-11-14T20:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_none_input(self):
        assert _parse_iso(None) is None

    def test_empty_string(self):
        assert _parse_iso("") is None

    def test_invalid_string(self):
        assert _parse_iso("not-a-timestamp") is None

    def test_z_and_offset_produce_same_result(self):
        a = _parse_iso("2025-11-14T20:00:00Z")
        b = _parse_iso("2025-11-14T20:00:00+00:00")
        assert a == b


# --- _build_tricode_map ---

class TestBuildTricodeMap:
    @pytest.fixture()
    def manifest(self):
        return {
            "away_team": "Brooklyn Nets",
            "home_team": "Orlando Magic",
        }

    def test_basic_mapping(self, manifest):
        events = [
            {"team_tricode": "BKN", "away_score": 2, "home_score": 0},
            {"team_tricode": "ORL", "away_score": 2, "home_score": 3},
        ]
        result = _build_tricode_map(events, manifest)
        assert result["BKN"] == "Brooklyn Nets"
        assert result["ORL"] == "Orlando Magic"

    def test_empty_events(self, manifest):
        assert _build_tricode_map([], manifest) == {}

    def test_no_tricode_field(self, manifest):
        events = [{"away_score": 2, "home_score": 0}]
        assert _build_tricode_map(events, manifest) == {}

    def test_tricode_not_reassigned(self, manifest):
        """Once a tricode is mapped, later events don't change it."""
        events = [
            {"team_tricode": "BKN", "away_score": 2, "home_score": 0},
            # Second event with same tricode and home score increase --
            # should NOT override the first mapping
            {"team_tricode": "BKN", "away_score": 2, "home_score": 3},
        ]
        result = _build_tricode_map(events, manifest)
        assert result["BKN"] == "Brooklyn Nets"

    def test_null_scores_treated_as_zero(self, manifest):
        events = [
            {"team_tricode": "BKN", "away_score": None, "home_score": None},
            {"team_tricode": "BKN", "away_score": 2, "home_score": 0},
        ]
        result = _build_tricode_map(events, manifest)
        assert result["BKN"] == "Brooklyn Nets"


class TestDeriveNbaFinalScore:
    def test_returns_last_event_scores(self):
        events = [
            {"away_score": 88, "home_score": 90},
            {"away_score": 101, "home_score": 99},
        ]
        assert _derive_nba_final_score(events) == (101, 99)

    def test_returns_none_for_missing_events(self):
        assert _derive_nba_final_score(None) is None
        assert _derive_nba_final_score([]) is None

    def test_returns_none_when_final_event_missing_scores(self):
        events = [{"away_score": 88, "home_score": 90}, {"away_score": 101}]
        assert _derive_nba_final_score(events) is None


class TestDeriveNbaFinalWinner:
    @pytest.fixture()
    def manifest(self):
        return {
            "away_team": "Brooklyn Nets",
            "home_team": "Orlando Magic",
        }

    def test_returns_away_team_when_away_score_higher(self, manifest):
        events = [{"away_score": 101, "home_score": 99}]
        assert _derive_nba_final_winner(manifest, events) == "Brooklyn Nets"

    def test_returns_home_team_when_home_score_higher(self, manifest):
        events = [{"away_score": 99, "home_score": 101}]
        assert _derive_nba_final_winner(manifest, events) == "Orlando Magic"

    def test_returns_none_for_tie_or_missing_scores(self, manifest):
        assert _derive_nba_final_winner(manifest, [{"away_score": 99, "home_score": 99}]) is None
        assert _derive_nba_final_winner(manifest, [{"away_score": 99}]) is None
        assert _derive_nba_final_winner(manifest, None) is None
