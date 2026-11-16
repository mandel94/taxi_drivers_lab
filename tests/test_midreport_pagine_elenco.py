"""
tests/test_midreport_pagine_elenco.py

Le pagine di elenco (categorie, archivi: /serie-tv, /festival-di-cinema, /page/32) non sono articoli:
non vanno attribuite per slug a un articolo con lo stesso nome (errore D-07 della KB).

Esecuzione: python -m pytest -q tests/test_midreport_pagine_elenco.py
"""

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

import midreport_client as mc  # noqa: E402


@pytest.mark.parametrize("path", ["/festival-di-cinema", "/serie-tv", "/latest-news", "/page/32", "/",
                                  "/festival-di-cinema/festival-dei-popoli", "/serie-tv/", "/serie-tv?page=2"])
def test_listing_paths(path):
    assert mc.is_listing_path(path)


@pytest.mark.parametrize("path", ["/365754/festival-di-cinema/festival-di-cinema.html",
                                  "/566494/festival-di-cinema/festival-dei-popoli/il-velo-dei-sensi.html",
                                  "/festival-di-cinema/berlinale/un-articolo-vecchio.html",
                                  "/123456/serie-tv/titolo"])
def test_article_paths_are_kept(path):
    assert not mc.is_listing_path(path)


def test_drop_listing_pages_filters_rows():
    pages = pd.DataFrame({mc.PAGE_PATH_COLUMN: ["/serie-tv", "/12/serie-tv/a.html", "/page/32"],
                          "activeUsers": ["41", "5", "6"]})
    out = mc.drop_listing_pages(pages)
    assert list(out[mc.PAGE_PATH_COLUMN]) == ["/12/serie-tv/a.html"]
