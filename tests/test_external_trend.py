"""
tests/test_external_trend.py

Segnali esterni del best of (scripts/external_trend.py, scripts/trend_best_of.py).
Le chiamate di rete sono sostituite da risposte finte: nessuna chiave TMDB necessaria.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_external_trend.py
"""

import datetime as dt
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ga4_client"))

import external_trend as ex  # noqa: E402
import trend_best_of as tb  # noqa: E402


def _fake_search(results):
    return lambda path, params, key: {"results": results}


def test_find_tmdb_matches_title_and_year(monkeypatch):
    results = [
        {"media_type": "person", "name": "Dio ride"},
        {"media_type": "movie", "id": 1, "title": "Dio ride", "release_date": "1990-01-01", "popularity": 9},
        {"media_type": "movie", "id": 2, "title": "Dio Ride", "original_title": "Dio Ride",
         "release_date": "2026-10-15", "popularity": 12.5},
    ]
    monkeypatch.setattr(ex, "_tmdb_get", _fake_search(results))
    item = ex.find_tmdb("dio ride", 2025, "k")
    assert item["id"] == 2 and item["year"] == 2026 and item["popularity"] == 12.5


def test_find_tmdb_matches_original_title_and_tv(monkeypatch):
    results = [{"media_type": "tv", "id": 7, "name": "Titolo italiano", "original_name": "Dead-End Job",
                "first_air_date": "2026-11-01", "popularity": 40}]
    monkeypatch.setattr(ex, "_tmdb_get", _fake_search(results))
    item = ex.find_tmdb("Dead End Job", 2025, "k")
    assert item["media_type"] == "tv" and item["id"] == 7


def test_find_tmdb_rejects_old_or_different(monkeypatch):
    results = [{"media_type": "movie", "id": 1, "title": "Altro", "release_date": "2026-01-01"},
               {"media_type": "movie", "id": 2, "title": "Matrix", "release_date": "1999-03-31"}]
    monkeypatch.setattr(ex, "_tmdb_get", _fake_search(results))
    assert ex.find_tmdb("Matrix", 2025, "k") is None


def test_snapshot_and_previous_popularity(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "SNAPSHOT_PATH", tmp_path / "snap.csv")
    item = {"id": 5, "media_type": "movie", "popularity": 10.0}
    ex.save_snapshot([item], dt.date(2026, 11, 1))
    ex.save_snapshot([dict(item, popularity=20.0)], dt.date(2026, 11, 5))
    ex.save_snapshot([dict(item, popularity=21.0)], dt.date(2026, 11, 5))  # stesso giorno: sostituisce
    assert ex.previous_popularity(item, dt.date(2026, 11, 8), 7) == 10.0
    assert ex.previous_popularity(item, dt.date(2026, 11, 8), 3) == 21.0
    assert ex.previous_popularity(item, dt.date(2026, 11, 3), 7) is None


def _clusters():
    base = {"section": "Sala", "prima_pubblicazione": pd.Timestamp("2026-10-01"),
            "momentum_nostro": 0.0, "editorial_score": 50.0}
    rows = [dict(base, titolo="Solo wiki"), dict(base, titolo="Wiki e tmdb"),
            dict(base, titolo="Solo tmdb"), dict(base, titolo="Niente")]
    c = pd.DataFrame(rows)
    for col in ("wiki_pagina", "tmdb_titolo"):
        c[col] = None
    for col in ("wiki_views", "wiki_recent", "wiki_prior", "momentum", "r_volume", "r_momentum",
                "tmdb_pop", "tmdb_pop_prev", "r_tmdb", "trend_score"):
        c[col] = np.nan
    c["fonte_score"] = ""
    c["cercato"] = True
    c.index = [f"Sala|{t}" for t in c["titolo"]]  # indice = cluster_id, come in build_clusters
    return c


def test_looks_like_work():
    assert tb._looks_like_work("Sala|dio ride", "Dio ride")  # titolo tra apici
    assert tb._looks_like_work("art:1", "Drive – The Pretenders")  # corto, senza segni di rassegna
    assert not tb._looks_like_work("art:2", "Sky novembre 2026: le serie TV in arrivo")
    assert not tb._looks_like_work("art:3", "FrontDoc 2026: ecco tutti i vincitori!")
    assert not tb._looks_like_work("art:4", "Un titolo molto lungo che non e' di sicuro il titolo di un film")


def test_add_external_combines_available_components(monkeypatch):
    pages = {"Solo wiki": 1000, "Wiki e tmdb": 5000}
    tmdb = {"Wiki e tmdb": 80.0, "Solo tmdb": 60.0}
    monkeypatch.setattr(ex, "tmdb_key", lambda: "k")
    monkeypatch.setattr(ex, "find_page", lambda label, y: (
        {"lang": "it", "title": label} if label in pages else None))
    monkeypatch.setattr(ex, "pageviews", lambda page, s, e: pd.Series(
        pages[page["title"]] / 28.0, index=pd.date_range(s, e)))
    monkeypatch.setattr(ex, "find_tmdb", lambda label, y, k: (
        {"id": 1, "media_type": "movie", "title": label, "year": 2026, "popularity": tmdb[label]}
        if label in tmdb else None))
    monkeypatch.setattr(ex, "previous_popularity", lambda *a: None)
    monkeypatch.setattr(ex, "save_snapshot", lambda *a: None)
    monkeypatch.setattr(ex, "save_cache", lambda: None)

    c = _clusters()
    tb._add_external(c, dt.date(2026, 10, 6), dt.date(2026, 11, 2), 7)
    by = c.set_index("titolo")
    assert by.loc["Wiki e tmdb", "fonte_score"] == "Esterno (Wikipedia + TMDB)"
    assert by.loc["Solo wiki", "fonte_score"] == "Esterno (Wikipedia)"
    assert by.loc["Solo tmdb", "fonte_score"] == "Esterno (TMDB)"
    assert by.loc["Niente", "trend_score"] != by.loc["Niente", "trend_score"]  # NaN
    # il piu' visto e piu' popolare sta sopra chi ha meno di entrambi
    assert by.loc["Wiki e tmdb", "trend_score"] > by.loc["Solo wiki", "trend_score"]
    assert by["trend_score"].dropna().between(0, 100).all()


# ------------------------------------------------------------ altre fonti (signal_sources)

import signal_sources as sm  # noqa: E402


def _ctx(tmp_path, monkeypatch, key="k"):
    monkeypatch.setattr(sm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sm, "SNAPSHOTS", tmp_path / "snapshots.csv")
    monkeypatch.setattr(sm.time, "sleep", lambda *_: None)
    return sm.Ctx(start=dt.date(2026, 10, 6), end=dt.date(2026, 11, 2), r=7, min_year=2025,
                  today=dt.date(2026, 11, 6), tmdb_key=key,
                  tmdb_items={"Sala|a": {"id": 5, "media_type": "movie"}})


def test_imdb_votes_via_tmdb_external_id(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "_tmdb_get", lambda path, params, key: {"imdb_id": "tt0001"})
    src = sm.Imdb(ctx)
    src.ratings = pd.DataFrame({"averageRating": [7.5], "numVotes": [1234]}, index=pd.Index(["tt0001"], name="tconst"))
    res = src.lookup("Sala|a", "A")
    assert res["imdb_id"] == "tt0001" and res["imdb_votes"] == 1234 and res["imdb_votes_prev"] is None
    assert src.lookup("Sala|senza-tmdb", "B") is None  # nessun item TMDB: nessun abbinamento


def test_imdb_skipped_without_tmdb_key(tmp_path, monkeypatch):
    assert sm.Imdb(_ctx(tmp_path, monkeypatch, key=None)).ok is False


def test_google_trends_ratio_and_momentum(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    src = sm.GoogleTrends(ctx)
    idx = pd.date_range(ctx.start, ctx.end)
    title = [10.0] * 14 + [10.0] * 7 + [40.0] * 7  # ultimi 7 giorni: 4x i 7 precedenti
    frame = pd.DataFrame({sm.GT_ANCHOR: [50.0] * 28, "Film": title, "isPartial": False}, index=idx)

    class Fake:
        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return frame

    src.client = Fake()
    res = src.lookup("c", "Film")
    assert abs(res["gt_ratio"] - (np.mean(title) / 50.0)) < 1e-9
    assert res["gt_momentum"] > 1.0
    assert src.lookup("c", "Film") == res  # seconda volta: dalla cache


def test_google_trends_stops_after_failures(tmp_path, monkeypatch):
    src = sm.GoogleTrends(_ctx(tmp_path, monkeypatch))

    class Broken:
        def build_payload(self, *a, **k):
            raise RuntimeError("429")

    src.client = Broken()
    assert src.lookup("c", "Film") is None and src.blocked
    assert src.lookup("c", "Altro") is None  # non riprova


def test_rotten_tomatoes_parse(tmp_path, monkeypatch):
    src = sm.RottenTomatoes(_ctx(tmp_path, monkeypatch))
    html = ('"dateCreated":"2026-10-01" "criticsScore":{"averageRating":"6.6","reviewCount":221,'
            '"scorePercent":"78%"} "audienceScore":{"bandedRatingCount":"2,500+","scorePercent":"94%"}')
    assert src._parse(html) == {"rt_critics": 78.0, "rt_reviews": 221.0, "rt_audience": 94.0}
    assert src._parse(html.replace("2026", "1999")) is None  # film vecchio con lo stesso titolo


def test_sources_without_key_are_skipped(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(sm, "_env", lambda name: None)
    assert sm.YouTube(ctx).ok is False and sm.Trakt(ctx).ok is False


def test_run_fills_separate_columns_and_ranks(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    c = _clusters()
    c["in_classifica"] = True
    votes = {"Solo wiki": 100.0, "Wiki e tmdb": 5000.0}
    monkeypatch.setattr(sm.Imdb, "lookup", lambda self, cid, label: (
        {"imdb_id": "tt", "imdb_votes": votes[label], "imdb_rating": 7.0, "imdb_votes_prev": None}
        if label in votes else None))
    monkeypatch.setattr(sm.Imdb, "close", lambda self: None)
    sm.run(c, ctx, ["imdb"])
    sm.add_ranks(c, tb._winsor_rank)
    by = c.set_index("titolo")
    assert by.loc["Wiki e tmdb", "imdb_votes"] == 5000.0 and np.isnan(by.loc["Niente", "imdb_votes"])
    assert by.loc["Wiki e tmdb", "r_imdb_votes"] > by.loc["Solo wiki", "r_imdb_votes"]
    assert np.isnan(by.loc["Niente", "r_imdb_votes"]) and np.isnan(by.loc["Solo wiki", "gt_ratio"])


def test_to_long_one_row_per_article_source_metric():
    c = _clusters()
    c.loc["Sala|Wiki e tmdb", ["wiki_views", "wiki_pagina", "tmdb_pop", "tmdb_titolo"]] = [
        5000.0, "it: X", 80.0, "movie: X (2026)"]
    c.loc["Sala|Solo wiki", ["wiki_views", "wiki_pagina"]] = [10.0, "it: Y"]
    sm.ensure_columns(c)
    arts = pd.DataFrame({"article_id": [1, 2, 3, 4], "cluster_id": [
        "Sala|Wiki e tmdb", "Sala|Wiki e tmdb", "Sala|Solo wiki", "Sala|Niente"]})
    out = sm.to_long(arts, c, dt.date(2026, 10, 6), dt.date(2026, 11, 2), dt.date(2026, 11, 6))
    assert set(out["article_id"]) == {1, 2, 3}  # 4 non ha segnali: nessuna riga
    wiki = out[(out["source"] == "wikipedia") & (out["metric"] == "views")].set_index("article_id")
    assert wiki.loc[1, "value"] == wiki.loc[2, "value"] == 5000.0  # valore dell'opera, ripetuto
    assert wiki.loc[1, "window_start"] == dt.date(2026, 10, 6)
    tm = out[out["source"] == "tmdb"]
    assert (tm["window_start"] == tm["window_end"]).all() and len(tm) == 2  # istantanea
    assert not out.duplicated(["article_id", "source", "metric"]).any()


def test_signals_table_has_one_column_per_source():
    cols = [h for _, h, _, _ in sm.COLUMNS]
    assert len(cols) == len(set(cols))
    assert set(sm.PRESENCE.values()) <= {c for c, *_ in sm.COLUMNS}
