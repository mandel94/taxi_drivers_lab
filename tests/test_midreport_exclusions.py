"""
tests/test_midreport_exclusions.py

Articoli esclusi per scelta editoriale dalla top del Midreport
(ga4_client/midreport_client.py, EXCLUDED_TITLE_PATTERNS).

Esecuzione (dalla root del repo):
    python -m pytest tests/test_midreport_exclusions.py
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from midreport_client import is_excluded_title  # noqa: E402


@pytest.mark.parametrize(
    "title",
    [
        "5 attrici famose che facevano le pornostar",
        "I migliori siti di film streaming gratis in italia",
        "Dove vedere film in streaming gratuito",
        "Film gratis in streaming: la guida",
    ],
)
def test_excluded_titles(title):
    assert is_excluded_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Apple TV, le novit&#224; di novembre 2026",
        "Sky novembre 2026: le serie TV, i film e i documentari in arrivo",
        "Le migliori attrici italiane",
        None,
    ],
)
def test_other_titles_are_kept(title):
    assert not is_excluded_title(title)
