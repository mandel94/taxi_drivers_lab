"""
tests/test_midreport_insight_fase2.py

Contratto di nlp/midreport_insight/arricchimento.py e inferenza.py (nlp/midreport_insight/README.md,
sezione fase 2). Nessuna rete: i segnali esterni usano un modulo finto.

Esecuzione: python -m pytest -q tests/test_midreport_insight_fase2.py
"""

import datetime as dt
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.midreport_insight import arricchimento as arr  # noqa: E402
from nlp.midreport_insight import inferenza as inf  # noqa: E402


def rec(role, topic, users, ratio, category="News", aid=1):
    return {"role": role, "topic": topic, "users": users, "ratio_vs_baseline": ratio,
            "category": category, "article_id": aid, "title": f"'{topic}' titolo"}


def test_select_topics_alternates_dedups_and_drops_quotes():
    rows = [rec("top", "A", 100, 5, aid=1), rec("top", "B", 50, 3, aid=2), rec("top", "A", 40, 2, aid=3),
            rec("worst", "C", 5, 0.4, aid=4), rec("worst", "D", 6, 0.5, aid=5),
            rec("worst", None, 4, 0.3, aid=6),
            rec("worst", "una frase lunghissima che e' una citazione e non un titolo", 3, 0.2, aid=7)]
    out = arr.select_topics(rows, max_topics=4)
    assert [t["topic"] for t in out] == ["A", "C", "B", "D"]
    assert out[0]["role"] == "top" and out[1]["role"] == "worst"


def test_news_queries_are_limited_and_mention_topic_and_month():
    topics = [{"topic": f"T{i}", "role": "top"} for i in range(15)]
    qs = arr.news_queries(topics, max_queries=10, today=dt.date(2026, 11, 16))
    assert len(qs) == 10
    assert qs[0]["topic"] == "T0" and "T0" in qs[0]["query"] and "novembre 2026" in qs[0]["query"]


class FakeExternal:
    def tmdb_key(self):
        return "k"

    def find_page(self, label, min_year):
        return {"lang": "it", "title": label} if label == "A" else None

    def pageviews(self, page, start, end):
        days = pd.date_range(start, end)
        vals = [10] * (len(days) - 7) + [40] * 7  # ultimi 7 giorni molto piu' alti
        return pd.Series(vals, index=days)

    def find_tmdb(self, label, min_year, key):
        return {"media_type": "tv", "title": label, "year": 2026, "popularity": 55.0} if label == "A" else None


def test_signals_momentum_and_missing_topic():
    out = arr.wiki_tmdb_signals([{"topic": "A"}, {"topic": "B"}], dt.date(2026, 11, 6), r=7, module=FakeExternal())
    assert out["A"]["fase"] == "in crescita" and out["A"]["momentum"] > 1
    assert out["A"]["tmdb_pop"] == 55.0 and out["A"]["wiki_page"] == "it: A"
    assert out["B"]["wiki_page"] is None and out["B"]["fase"] is None


def test_merge_attaches_signals_and_news():
    rows = [rec("top", "A", 100, 5), rec("worst", "B", 5, 0.4)]
    merged = arr.merge_enrichment(rows, {"A": {"fase": "in crescita"}},
                                  {"A": [{"titolo": "Rinnovata", "rilevante": True}]})
    assert merged[0]["segnali"]["fase"] == "in crescita" and merged[0]["notizie"][0]["titolo"] == "Rinnovata"
    assert merged[1]["segnali"] is None and merged[1]["notizie"] == []


def test_classify_claim_follows_repetition_rules():
    assert inf.classify_claim(n=8, weeks_with_data=1, weeks_same_direction=1)["stato"] == "fatto"
    assert inf.classify_claim(n=8, weeks_with_data=3, weeks_same_direction=1)["stato"] == "ipotesi"
    mid = inf.classify_claim(n=6, weeks_with_data=3, weeks_same_direction=3)
    assert mid == {"stato": "pattern", "confidenza": "media"}
    assert inf.classify_claim(n=9, weeks_with_data=5, weeks_same_direction=5)["confidenza"] == "alta"
    assert inf.classify_claim(n=2, weeks_with_data=3, weeks_same_direction=3)["stato"] == "ipotesi"


def obs():
    cats = [
        {"category": "Interviste", "n_articles": 17, "users": 472, "share_pct": 9.9, "normal_share_pct": 4.6,
         "share_ratio": 2.1, "direction": "su", "top1_title": "X", "top1_share_of_category": 0.4,
         "n_history_weeks": 5, "sample_ok": True, "fact": "Interviste: quota 9,9%."},
        {"category": "News", "n_articles": 39, "users": 455, "share_pct": 9.5, "normal_share_pct": 10.6,
         "share_ratio": 0.9, "direction": "stabile", "top1_title": "Y", "top1_share_of_category": 0.08,
         "n_history_weeks": 5, "sample_ok": True, "fact": "News: quota 9,5%."},
        {"category": "Rubriche", "n_articles": 2, "users": 32, "share_pct": 0.7, "normal_share_pct": None,
         "share_ratio": None, "direction": None, "top1_title": "Z", "top1_share_of_category": 0.5,
         "n_history_weeks": 2, "sample_ok": False, "fact": "Rubriche: 2 articoli."},
    ]
    pats = [
        {"dimension": "pub_weekday", "value": "dom", "n": 25, "median_ratio": 1.56, "notable": True,
         "weeks_with_data": 6, "weeks_same_direction": 6, "fact": "dom: 25 articoli."},
        {"dimension": "author", "value": "Angela Failla", "n": 9, "median_ratio": 1.57, "notable": True,
         "weeks_with_data": 2, "weeks_same_direction": 2, "fact": "autrice: 9 articoli."},
        {"dimension": "format", "value": "news", "n": 30, "median_ratio": 1.0, "notable": False,
         "weeks_with_data": 6, "weeks_same_direction": 3, "fact": "news."},
    ]
    return {"categories": cats, "patterns": pats}


def test_candidates_only_moves_and_notable_patterns_with_confounders():
    cands = inf.candidate_insights(obs())
    kinds = [(c["tipo"], c.get("categoria") or c.get("dimensione")) for c in cands]
    assert ("categoria", "Interviste") in kinds and ("categoria", "News") not in kinds
    assert ("categoria", "Rubriche") not in kinds
    assert ("pattern", "pub_weekday") in kinds and ("pattern", "format") not in kinds
    cat = next(c for c in cands if c.get("categoria") == "Interviste")
    assert any("X" in c for c in cat["confondenti"])  # top1 al 40%: trainato da X
    pat = {c["dimensione"]: c for c in cands if c["tipo"] == "pattern"}
    assert pat["pub_weekday"]["stato"] == "pattern" and pat["author"]["stato"] == "ipotesi"
    assert any("autore" in c.lower() or "argoment" in c.lower() for c in pat["author"]["confondenti"])


def good():
    return {"fatto": "Interviste 9,9% degli utenti contro 4,6% normale.", "ipotesi": "Due interviste a registi.",
            "consiglio": "Provare la coppia recensione e intervista.", "confidenza": "bassa", "stato": "ipotesi",
            "evidenza": ["472 utenti su 17 articoli"]}


def test_validate_insight():
    assert inf.validate_insight(good()) == []
    bad = dict(good(), fatto="Interviste in crescita", confidenza="certa")
    errs = inf.validate_insight(bad)
    assert any("numero" in e for e in errs) and any("confidenza" in e for e in errs)
    assert any("dati" in e for e in inf.validate_insight(dict(good(), fatto="Il sito e' stato bloccato, 3 giorni.")))
    del_key = {k: v for k, v in good().items() if k != "consiglio"}
    assert any("consiglio" in e for e in inf.validate_insight(del_key))
