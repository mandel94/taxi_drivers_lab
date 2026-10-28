"""
tests/test_category_mapping.py

Test di ga4_client/category_mapping.py contro le regole di td_report/map_ga4_categories.py.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_category_mapping.py
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from category_mapping import map_category  # noqa: E402


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/559682/latest-news/la-mummia-4.html", "News"),
        ("/558461/festival-di-cinema/vision2030/in-gaza.html", "Festival di Cinema"),
        ("/520810/taxidrivers-magazine/valery.html", "Speciali e Magazine"),
        ("/521186/serie-tv/paramount-serie-tv/the-madison.html", "Serie TV"),
        ("/560495/latest-news/si-fara/slow-horses-7.html", "Si farà"),
        ("/520498/review/in-sala/amrum.html", "Recensioni"),
        ("/520498/review/in-sala/amrum.html", "Recensioni"),
        ("/some/unknown/page.html", "Altro"),
        ("/", "Altro"),
    ],
)
def test_map_category(path, expected):
    assert map_category(path) == expected
