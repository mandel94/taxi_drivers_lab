"""
tests/test_trend_publish_sources.py

Fonti dei candidati del Trend Radar (nlp/trend_publish/sources.py): database,
API di WordPress e unione. Le fonti sono funzioni iniettate: qui sono finte e
registrano le chiamate. Nessun database, nessuna rete.
Contratto: nlp/trend_publish/README.md.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_sources.py
"""

import copy
import pathlib
import sys
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.trend_publish.sources import (  # noqa: E402
    candidates_from_db,
    candidates_from_wp,
    merge_candidates,
)

LINK_BD2 = "https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html"
LINK_BD3 = "https://www.taxidrivers.it/564791/latest-news/si-fara/black-doves-3.html"
LINK_BD1 = "https://www.taxidrivers.it/414748/serie-tv/black-doves.html"


# ---------------------------------------------------------------------------
# candidates_from_db
# ---------------------------------------------------------------------------

class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, sql, params):
        self.calls.append((sql, params))
        return copy.deepcopy(self.rows)


ENTITY_DB = {"title": "Black Doves", "aliases": ["Colombe Nere"], "season": 2}

RIGHE_DB = [
    {"article_id": 564645, "title": "'Black Doves 2' , il ritorno dello spionaggio Pulp", "link": LINK_BD2,
     "pub_date": datetime(2026, 11, 6, 10, 30), "editorial_score": 71.6, "active_users": 35},
    {"article_id": 564791, "title": "&#8216;Black Doves 3&#8217;: ci sar&agrave;?", "link": LINK_BD3,
     "pub_date": date(2026, 11, 7), "editorial_score": 65.4, "active_users": 58},
    {"article_id": 564645, "title": "'Black Doves 2' , il ritorno dello spionaggio Pulp", "link": LINK_BD2,
     "pub_date": datetime(2026, 11, 6, 10, 30), "editorial_score": 60.0, "active_users": 20},
    {"article_id": 414748, "title": "'Black Doves': Spionaggio, Vendetta e Azione", "link": LINK_BD1,
     "pub_date": datetime(2024, 11, 30, 8, 0), "editorial_score": None, "active_users": None},
]


def _da_db(righe=RIGHE_DB, entity=ENTITY_DB):
    q = FakeQuery(righe)
    return q, candidates_from_db(q, entity)


def _per_id(candidati):
    return {c["article_id"]: c for c in candidati}


def test_db_una_sola_chiamata_con_le_tabelle_e_la_versione_attese():
    q, _ = _da_db()
    assert len(q.calls) == 1
    sql, params = q.calls[0]
    assert isinstance(sql, str)
    assert "articles_dim" in sql
    assert "fact_article_score_period" in sql
    assert "balanced-v2" in sql
    assert "ILIKE" in sql.upper()
    assert isinstance(params, dict)


def test_db_i_parametri_contengono_titolo_e_alias():
    q, _ = _da_db()
    _, params = q.calls[0]
    valori = " | ".join(str(v) for v in params.values())
    assert "Black Doves" in valori
    assert "Colombe Nere" in valori


def test_db_senza_alias_e_senza_stagione_funziona():
    q, out = _da_db(RIGHE_DB[:1], {"title": "Black Doves"})
    assert len(q.calls) == 1
    assert len(out) == 1


def test_db_raggruppa_le_righe_dello_stesso_articolo():
    _, out = _da_db()
    assert [c["article_id"] for c in out] == [564645, 564791, 414748]
    bd2 = _per_id(out)[564645]
    proiezione = [(s["editorial_score"], s["active_users"]) for s in bd2["scores"]]
    assert proiezione == [(71.6, 35), (60.0, 20)]


def test_db_formato_del_candidato():
    _, out = _da_db()
    bd2 = _per_id(out)[564645]
    assert bd2["link"] == LINK_BD2
    assert bd2["title"] == "'Black Doves 2' , il ritorno dello spionaggio Pulp"
    assert {"article_id", "title", "link", "pub_date", "scores"} <= set(bd2)


def test_db_righe_senza_punteggio_hanno_scores_vuoto():
    _, out = _da_db()
    assert _per_id(out)[414748]["scores"] == []


def test_db_pub_date_diventa_date_anche_da_datetime():
    _, out = _da_db()
    per_id = _per_id(out)
    assert type(per_id[564645]["pub_date"]) is date
    assert per_id[564645]["pub_date"] == date(2026, 11, 6)
    assert type(per_id[564791]["pub_date"]) is date
    assert per_id[564791]["pub_date"] == date(2026, 11, 7)
    assert per_id[414748]["pub_date"] == date(2024, 11, 30)


def test_db_titolo_con_entita_html_viene_unescaped():
    _, out = _da_db()
    assert _per_id(out)[564791]["title"] == "‘Black Doves 3’: ci sarà?"


def test_db_nessuna_riga_nessun_candidato():
    q, out = _da_db([])
    assert out == []
    assert len(q.calls) == 1


# ---------------------------------------------------------------------------
# candidates_from_wp
# ---------------------------------------------------------------------------

ENTITY_WP = {
    "title": "Gli Anelli del Potere",
    "aliases": ["Il Signore degli Anelli: Gli Anelli del Potere"],
    "season": 3,
}
SINCE = date(2026, 11, 1)


def post(article_id, rendered, data="2026-11-08T09:15:00", sezione="latest-news"):
    return {
        "id": article_id,
        "date": data,
        "link": f"https://www.taxidrivers.it/{article_id}/{sezione}/articolo.html",
        "title": {"rendered": rendered},
    }


class FakeHttp:
    """Registra gli url e risponde con una lista per chiamata (in ordine)."""

    def __init__(self, risposte):
        self.risposte = list(risposte)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        i = len(self.urls) - 1
        return copy.deepcopy(self.risposte[i]) if i < len(self.risposte) else []


def _query(url):
    return parse_qs(urlsplit(url).query)


def test_wp_un_url_per_titolo_e_uno_per_ogni_alias():
    http = FakeHttp([[], []])
    candidates_from_wp(http, ENTITY_WP, SINCE)
    assert len(http.urls) == 2
    cercati = [_query(u)["search"][0] for u in http.urls]
    assert cercati == ["Gli Anelli del Potere", "Il Signore degli Anelli: Gli Anelli del Potere"]


def test_wp_solo_titolo_senza_alias_una_chiamata():
    http = FakeHttp([[]])
    candidates_from_wp(http, {"title": "Odissea"}, SINCE)
    assert len(http.urls) == 1


def test_wp_parametri_dell_url():
    http = FakeHttp([[], []])
    candidates_from_wp(http, ENTITY_WP, SINCE)
    for url in http.urls:
        assert "/wp-json/wp/v2/posts" in urlsplit(url).path
        q = _query(url)
        assert q["per_page"] == ["20"]
        assert q["after"] == ["2026-11-01T00:00:00"]
        assert q["_fields"] == ["id,date,link,title"]


def test_wp_il_termine_di_ricerca_e_codificato_nell_url():
    http = FakeHttp([[], []])
    candidates_from_wp(http, ENTITY_WP, SINCE)
    grezzo = [u.split("search=", 1)[1].split("&", 1)[0] for u in http.urls]
    for valore in grezzo:
        assert " " not in valore
        assert "%20" in valore or "+" in valore
    # nell'alias i due punti sono codificati
    assert ":" not in grezzo[1]
    assert "%3A" in grezzo[1].upper()


def test_wp_formato_dei_candidati_con_titolo_unescaped():
    http = FakeHttp([[post(565040, "&#8216;Gli Anelli del Potere 3&#8217;: ci sar&agrave;?")], []])
    out = candidates_from_wp(http, ENTITY_WP, SINCE)
    assert len(out) == 1
    c = out[0]
    assert c["article_id"] == 565040
    assert c["title"] == "‘Gli Anelli del Potere 3’: ci sarà?"
    assert c["link"] == "https://www.taxidrivers.it/565040/latest-news/articolo.html"
    assert c["pub_date"] == date(2026, 11, 8)
    assert type(c["pub_date"]) is date
    assert c["scores"] == []


def test_wp_deduplica_per_article_id_tra_ricerche_diverse():
    doppio = post(565040, "‘Gli Anelli del Potere 3’, svelato il trailer ufficiale")
    http = FakeHttp([
        [doppio, post(565041, "‘Gli Anelli del Potere’: nuove foto")],
        [doppio, post(565042, "La terza stagione de 'Il Signore degli Anelli: gli Anelli del Potere'")],
    ])
    out = candidates_from_wp(http, ENTITY_WP, SINCE)
    assert [c["article_id"] for c in out] == [565040, 565041, 565042]


def test_wp_nessun_risultato():
    assert candidates_from_wp(FakeHttp([[], []]), ENTITY_WP, SINCE) == []


# ---------------------------------------------------------------------------
# merge_candidates
# ---------------------------------------------------------------------------

def c(article_id, origine, scores=()):
    return {
        "article_id": article_id,
        "title": f"titolo {origine}",
        "link": f"https://www.taxidrivers.it/{article_id}/latest-news/{origine}.html",
        "pub_date": date(2026, 11, 1),
        "scores": list(scores),
    }


def test_merge_unione_per_article_id_vince_la_riga_db():
    db = [c(1, "db", [{"editorial_score": 70.0, "active_users": 30}]), c(2, "db")]
    wp = [c(2, "wp"), c(3, "wp")]
    out = merge_candidates(db, wp)
    assert [x["article_id"] for x in out] == [1, 2, 3]
    per_id = {x["article_id"]: x for x in out}
    assert per_id[2]["title"] == "titolo db"
    assert per_id[3]["title"] == "titolo wp"
    assert per_id[1]["scores"] == [{"editorial_score": 70.0, "active_users": 30}]


def test_merge_ordine_stabile_prima_db_poi_wp():
    db = [c(5, "db"), c(1, "db")]
    wp = [c(9, "wp"), c(3, "wp"), c(5, "wp")]
    out = merge_candidates(db, wp)
    assert [x["article_id"] for x in out] == [5, 1, 9, 3]


def test_merge_liste_vuote():
    assert merge_candidates([], []) == []
    solo_wp = [c(3, "wp"), c(4, "wp")]
    assert merge_candidates([], solo_wp) == solo_wp
    solo_db = [c(1, "db")]
    assert merge_candidates(solo_db, []) == solo_db


def test_merge_non_modifica_gli_argomenti():
    db = [c(1, "db"), c(2, "db")]
    wp = [c(2, "wp"), c(3, "wp")]
    db_prima, wp_prima = copy.deepcopy(db), copy.deepcopy(wp)
    merge_candidates(db, wp)
    assert db == db_prima
    assert wp == wp_prima


# ---------------------------------------------------------------------------
# candidates_from_db: NULL del database che arrivano come float("nan") da pandas
# (DataFrame.to_dict("records")), non come None
# ---------------------------------------------------------------------------

NAN = float("nan")
TITOLO_BD2 = "'Black Doves 2' , il ritorno dello spionaggio Pulp"


def _riga_pandas(editorial_score, active_users):
    return {
        "article_id": 564645, "title": TITOLO_BD2, "link": LINK_BD2,
        "pub_date": datetime(2026, 11, 6, 10, 0),
        "editorial_score": editorial_score, "active_users": active_users,
    }


def _proiezione(candidato):
    return [
        {"editorial_score": s["editorial_score"], "active_users": s["active_users"]}
        for s in candidato["scores"]
    ]


def test_db_nan_di_pandas_in_una_settimana_senza_punteggio_viene_ignorato():
    righe = [_riga_pandas(NAN, NAN), _riga_pandas(71.6, 35.0)]
    _, out = _da_db(righe, {"title": "Black Doves"})
    assert len(out) == 1
    assert out[0]["article_id"] == 564645
    assert _proiezione(out[0]) == [{"editorial_score": 71.6, "active_users": 35}]


def test_db_nan_di_pandas_su_unico_articolo_da_scores_vuoto():
    _, out = _da_db([_riga_pandas(NAN, NAN)], {"title": "Black Doves"})
    assert len(out) == 1
    assert out[0]["scores"] == []


def test_db_nan_di_pandas_su_active_users_vale_zero():
    _, out = _da_db([_riga_pandas(65.4, NAN)], {"title": "Black Doves"})
    assert len(out) == 1
    assert _proiezione(out[0]) == [{"editorial_score": 65.4, "active_users": 0}]
