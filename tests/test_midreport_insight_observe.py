"""
tests/test_midreport_insight_observe.py

Fase 1 del modulo di insight del midreport: osservazioni (fatti, nessuna causa).
Contratto: nlp/midreport_insight/README.md. History sintetica, niente KB ne' rete.

Esecuzione (dalla radice del repo):
    .venv\\Scripts\\python.exe -m pytest -q tests/test_midreport_insight_observe.py
"""

import json
import math
import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.midreport_insight import observe  # noqa: E402

LSQ = "‘"
RSQ = "’"
CUR = "2026-11-02"
PREV = "2026-10-19"  # ultima settimana comparabile prima di CUR
NON_COMP = "2026-10-26"
PAST_COMPARABLE = ["2026-09-28", "2026-10-05", "2026-10-12", PREV]


def _row(week_id, article_id, title, category, pub_date, users,
         comparable=True, excluded=False, er=0.1, author="Anna"):
    start = pd.Timestamp(week_id)
    return {
        "week_id": week_id,
        "period_start": week_id,
        "period_end": (start + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
        "window_days": 7,
        "comparable": comparable,
        "article_id": article_id,
        "title": title,
        "author": author,
        "category": category,
        "pub_date": pub_date,
        "users": users,
        "er": er,
        "dur": 60.0,
        "excluded": excluded,
    }


def _day(week_id, offset):
    return (pd.Timestamp(week_id) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def history():
    """4 settimane comparabili passate (3 categorie x 5 articoli x 100 utenti),
    1 non comparabile (dati che falserebbero la baseline), la settimana corrente."""
    rows = []
    for wk in PAST_COMPARABLE:
        for cat, tpl in (("News", "Notizia passata"),
                         ("Recensioni", "Titolo recensioni"),
                         ("Anticipazioni", "Titolo anticipazioni")):
            for i in range(5):
                aid = f"{cat[:3]}-{wk}-{i}"
                if cat == "Recensioni" and wk == PREV and i == 1:
                    aid = "r2"  # pub 2026-10-20, ricompare nella settimana corrente
                rows.append(_row(wk, aid, f"{tpl} {i}", cat, _day(wk, i), 100))

    # settimana non comparabile: non deve entrare ne' in baseline ne' in prev_*
    rows.append(_row(NON_COMP, "r2", "Titolo recensioni 1", "Recensioni", "2026-10-20", 1,
                     comparable=False))
    for i in range(5):
        rows.append(_row(NON_COMP, f"tn-{i}", f"Trailer passato {i}", "Trailers",
                         _day(NON_COMP, i), 9999, comparable=False))

    # settimana corrente (2026-11-02 .. 2026-11-08)
    news = [("n1", "2026-11-02", 300), ("n2", "2026-11-02", 200), ("n3", "2026-11-03", 150),
            ("n4", "2026-11-06", 100), ("n5", "2026-11-07", 50)]
    for aid, pub, users in news:
        rows.append(_row(CUR, aid, f"Notizia corrente {aid}", "News", pub, users))
    rec = [("r1", "2026-10-30"), ("r2", "2026-10-20"), ("r3", "2026-09-01"),
           ("r4", "2026-11-03"), ("r5", "2026-11-04")]
    for aid, pub in rec:
        rows.append(_row(CUR, aid, f"Titolo recensioni {aid}", "Recensioni", pub, 40))
    for aid, users in zip(["a1", "a2", "a3", "a4", "a5"], [140, 120, 100, 80, 60]):
        rows.append(_row(CUR, aid, f"Titolo anticipazioni {aid}", "Anticipazioni",
                         "2026-11-02", users))
    for k in range(1, 6):  # categoria presente solo questa settimana, articoli vecchi
        rows.append(_row(CUR, f"f{k}", f"Festival di prova {k}", "Festival di Cinema",
                         "2026-09-01", 20))
    rows.append(_row(CUR, "t1", "Trailer di prova uno", "Trailers", "2026-11-02", 50))
    rows.append(_row(CUR, "t2", "Trailer di prova due", "Trailers", "2026-11-03", 50))
    rows.append(_row(CUR, "x1", "Notizia esclusa", "News", "2026-11-02", 99999, excluded=True))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def table(history):
    return observe.build_table(history, CUR)


def _news_history(users_by_week):
    """Solo News, 6 articoli per settimana, tutti uguali in utenti, tutte comparabili."""
    rows = []
    for wk, users in users_by_week.items():
        for i in range(6):
            rows.append(_row(wk, f"{wk}-{i}", f"Notizia {wk} {i}", "News", _day(wk, i), users))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- classify_format

@pytest.mark.parametrize(
    "title, category, expected",
    [
        ("Parliamo con il regista", "Interviste", "intervista"),
        ("L'INTERVISTA a Rossi", "news", "intervista"),
        ("Intervista con il trailer", "Trailers", "intervista"),          # 1 batte 2
        ("Titolo qualunque", "Trailers", "trailer"),
        ("Il nuovo trailer di Dune", "News", "trailer"),
        ("10 serie tv sugli zombie", "News", "guida_lista"),
        ("I 10 film Netflix", "News", "guida_lista"),
        ("  Top 5 commedie", "News", "guida_lista"),
        ("I migliori film del momento", "News", "guida_lista"),
        ("Dove vedere Dune", "News", "guida_lista"),
        ("Disney+ Novembre 2026", "News", "guida_lista"),
        (f"{LSQ}2001{RSQ} torna al cinema", "News", "news"),              # virgolette: no lista
        ("10 migliori recensioni", "Recensioni", "guida_lista"),          # 3 batte 4
        ("Titolo qualunque", "Recensioni", "recensione"),
        ("Recensione di Dune", "News", "recensione"),
        ("Titolo qualunque", "Si farà", "si_fara"),
        ("Il sequel si farà davvero", "News", "si_fara"),
        ("Titolo qualunque", "Anticipazioni", "anticipazione"),
        ("Titolo qualunque", "Festival di Cinema", "festival"),
        ("Titolo qualunque", "News", "news"),
        ("Titolo qualunque", "Varie", "altro"),
    ],
)
def test_classify_format(title, category, expected):
    assert observe.classify_format(title, category) == expected


# ---------------------------------------------------------------- extract_topic

def test_extract_topic_apostrofo_interno_non_chiude():
    title = f"Su {LSQ}Highlander – L{RSQ}ultimo immortale{RSQ} al cinema"
    assert observe.extract_topic(title) == f"Highlander – L{RSQ}ultimo immortale"


def test_extract_topic_senza_virgolette_e_none():
    assert observe.extract_topic("Titolo senza virgolette") is None


# ---------------------------------------------------------------- title_features

def test_title_features_segnali_e_topic():
    title = f"I 10 film Netflix: {LSQ}Dune{RSQ} e' il migliore?"
    f = observe.title_features(title)
    assert f["has_question"] is True
    assert f["starts_with_number"] is True
    assert f["has_colon"] is True
    assert f["n_chars"] == len(title)
    assert f["length_bucket"] == "corto"
    assert f["topic"] == "Dune"


@pytest.mark.parametrize("n, bucket", [(49, "corto"), (50, "medio"), (80, "medio"), (81, "lungo")])
def test_title_features_length_bucket(n, bucket):
    assert observe.title_features("a" * n)["length_bucket"] == bucket


# ---------------------------------------------------------------- build_table

def test_build_table_esclusi_fuori_e_una_riga_per_articolo(table):
    assert len(table) == 22
    assert "x1" not in set(table["article_id"])


def test_build_table_baseline_esclude_settimana_corrente_e_non_comparabili(table):
    t = table.set_index("article_id")
    # News in_settimana: mediana delle 4 settimane comparabili passate = 100
    assert t.loc["n1", "baseline_users"] == 100
    assert t.loc["n1", "ratio_vs_baseline"] == pytest.approx(3.0)
    # Trailers: gli unici dati storici stanno nella settimana non comparabile -> NaN
    assert math.isnan(t.loc["t1", "baseline_users"])
    assert math.isnan(t.loc["t1", "ratio_vs_baseline"])
    # Festival: gli unici dati stanno nella settimana corrente -> NaN
    assert math.isnan(t.loc["f1", "baseline_users"])


def test_build_table_age_group(table):
    t = table.set_index("article_id")
    assert t.loc["n1", "age_group"] == "in_settimana"
    assert t.loc["r1", "age_group"] == "1-7gg"
    assert t.loc["r2", "age_group"] == "8-30gg"
    assert t.loc["r3", "age_group"] == "oltre_30gg"
    assert t.loc["r2", "age_days"] == 13


def test_build_table_exposure_days(table):
    t = table.set_index("article_id")
    assert t.loc["n1", "exposure_days"] == 7
    assert t.loc["n4", "exposure_days"] == 3   # 6, 7, 8 novembre inclusi
    assert t.loc["n5", "exposure_days"] == 2
    assert t.loc["r2", "exposure_days"] == 7   # pubblicato prima: tutto il periodo


def test_build_table_prev_users_salta_settimana_non_comparabile(table):
    t = table.set_index("article_id")
    assert t.loc["r2", "prev_week_id"] == PREV
    assert t.loc["r2", "prev_users"] == 100     # non 1, che e' nella settimana non comparabile
    assert math.isnan(t.loc["n1", "prev_users"])


# ---------------------------------------------------------------- category_observations

def test_category_observations_share_e_ordine(table, history):
    obs = observe.category_observations(table, history, CUR)
    by_cat = {o["category"]: o for o in obs}
    assert [o["category"] for o in obs][0] == "News"
    shares = [o["share_pct"] for o in obs]
    assert shares == sorted(shares, reverse=True)
    news = by_cat["News"]
    assert news["n_articles"] == 5
    assert news["users"] == 800                       # l'escluso non conta
    assert news["share_pct"] == pytest.approx(800 / 1700 * 100)
    assert news["normal_share_pct"] == pytest.approx(100 / 3, abs=0.5)
    assert news["sample_ok"] is True


def test_category_observations_direction_su_giu_stabile(table, history):
    by_cat = {o["category"]: o for o in observe.category_observations(table, history, CUR)}
    assert by_cat["News"]["direction"] == "su"             # quota ~47% vs ~33%
    assert by_cat["Recensioni"]["direction"] == "giu"      # quota ~12% vs ~33%
    assert by_cat["Anticipazioni"]["direction"] == "stabile"  # quota ~29% vs ~33%


def test_category_observations_storico_corto_o_campione_piccolo_none(table, history):
    by_cat = {o["category"]: o for o in observe.category_observations(table, history, CUR)}
    fest = by_cat["Festival di Cinema"]               # nessuna settimana di storico
    assert fest["direction"] is None
    assert fest["normal_share_pct"] is None
    assert fest["z"] is None
    tr = by_cat["Trailers"]                           # solo 2 articoli
    assert tr["sample_ok"] is False
    assert tr["direction"] is None


# ---------------------------------------------------------------- select_top_worst

def test_select_top_worst_nessun_worst_con_esposizione_breve(table):
    tw = observe.select_top_worst(table)
    worst = tw[tw["role"] == "worst"]
    assert "n5" not in set(worst["article_id"])        # ratio 0.5 ma esposto 2 giorni
    assert (worst["exposure_days"] >= 3).all()
    assert set(worst[worst["category"] == "News"]["article_id"]) == {"n3", "n4"}
    top_news = tw[(tw["role"] == "top") & (tw["category"] == "News")]
    assert set(top_news["article_id"]) == {"n1", "n2"}


def test_select_top_worst_salta_categorie_con_meno_di_5_articoli(table):
    tw = observe.select_top_worst(table)
    assert "Trailers" not in set(tw["category"])
    assert "News" in set(tw["category"])


# ---------------------------------------------------------------- pattern_observations

@pytest.fixture(scope="module")
def pattern_history():
    # baseline di ogni settimana = mediana delle altre quattro: 3 passate sotto, 2 sopra
    return _news_history({"2026-10-05": 100, "2026-10-12": 100, "2026-10-19": 100,
                          "2026-10-26": 400, CUR: 200})


def test_pattern_observations_min_n(pattern_history):
    t = observe.build_table(pattern_history, CUR)
    pats = observe.pattern_observations(t, pattern_history, CUR)
    fmt = [p for p in pats if p["dimension"] == "format" and p["value"] == "news"]
    assert len(fmt) == 1
    assert fmt[0]["n"] == 6
    assert fmt[0]["median_ratio"] == pytest.approx(2.0)
    assert fmt[0]["notable"] is True
    # con min_n piu' alto del campione il valore sparisce
    pats_hi = observe.pattern_observations(t, pattern_history, CUR, min_n=7)
    assert [p for p in pats_hi if p["dimension"] == "format"] == []


def test_pattern_observations_weeks_same_direction(pattern_history):
    t = observe.build_table(pattern_history, CUR)
    pats = observe.pattern_observations(t, pattern_history, CUR)
    p = [x for x in pats if x["dimension"] == "format" and x["value"] == "news"][0]
    assert p["weeks_with_data"] == 5        # 4 passate + la corrente
    # sopra 1 come la corrente (ratio 2.0): solo 2026-10-26 (ratio 4.0) e la corrente stessa
    assert p["weeks_same_direction"] == 2


# ---------------------------------------------------------------- observe_week

def test_observe_week_chiavi_e_flags(history):
    res = observe.observe_week(history, CUR)
    assert set(res) >= {"week_id", "comparable", "n_articles", "n_history_weeks",
                        "categories", "patterns", "top_worst", "flags"}
    assert res["week_id"] == CUR
    assert res["comparable"] is True
    assert res["n_articles"] == 22
    assert res["n_history_weeks"] == 4
    assert isinstance(res["categories"], list) and isinstance(res["top_worst"], list)
    assert any("pub_hour" in f for f in res["flags"])   # la history di test non ha pub_hour
    json.dumps(res)                                      # serializzabile, date in ISO


def test_observe_week_flag_settimana_non_comparabile(history):
    res = observe.observe_week(history, NON_COMP)
    assert res["comparable"] is False
    assert any("comparabil" in f.lower() for f in res["flags"])


def test_traffico_sospetto_non_entra_in_tabella_ne_in_baseline(history):
    bot = _row(CUR, 9001, "Pagina vecchia", "News", "2020-01-01", 150, er=0.0)
    bot["dur"] = 0.0
    bot_old = _row(PREV, 9002, "Pagina vecchia 2", "News", "2020-01-01", 150, er=0.0)
    bot_old["dur"] = 0.0
    h = pd.concat([history, pd.DataFrame([bot, bot_old])], ignore_index=True)
    t = observe.build_table(h, CUR)
    assert 9001 not in set(t["article_id"])
    assert len(t) == len(observe.build_table(history, CUR))
    # sotto i 20 utenti la riga resta: la regola della KB vale da 20 utenti attivi
    small = _row(CUR, 9003, "Pagina piccola", "News", "2020-01-01", 15, er=0.0)
    small["dur"] = 0.0
    h2 = pd.concat([history, pd.DataFrame([small])], ignore_index=True)
    assert 9003 in set(observe.build_table(h2, CUR)["article_id"])
