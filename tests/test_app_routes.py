"""Routes/navbar wiring smoke tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import PAGES, band_drop_recovery_page
from view_helpers import build_navbar


def test_band_drop_recovery_route_registered():
    assert "/nba-band-drop-recovery" in PAGES
    assert PAGES["/nba-band-drop-recovery"] is band_drop_recovery_page


def test_band_drop_recovery_in_navbar():
    navbar = build_navbar("/")
    rendered = str(navbar)
    assert "/nba-band-drop-recovery" in rendered
    assert "NBA Band Drop Recovery" in rendered
