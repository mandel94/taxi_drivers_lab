"""
tests/test_trend_publish_resolver.py

Scelta degli articoli interni del Trend Radar (nlp/trend_publish/link_resolver.py):
titoli tra virgolette, corrispondenza con l'entita', soglia dei punteggi e
regole di scelta. Contratto: nlp/trend_publish/README.md.
Funzioni pure: niente database, niente rete. I casi sono articoli reali di
taxidrivers.it; "oggi" e' fissato al 15 novembre 2026.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_resolver.py
"""

import copy
import pathlib
import sys
from datetime import date

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.trend_publish.link_resolver import (  # noqa: E402
    Choice,
    choose_article,
    choose_si_fara,
    eligible_score,
    is_si_fara,
    matches_entity,
    normalize_title,
    quoted_titles,
    section_of,
)

OGGI = date(2026, 11, 15)


def cand(article_id, title, section, pub_date, scores=(), slug="articolo"):
    """Candidato nel formato di choose_article; section puo' contenere 'latest-news/si-fara'."""
    return {
        "article_id": article_id,
        "title": title,
        "link": f"https://www.taxidrivers.it/{article_id}/{section}/{slug}.html",
        "pub_date": pub_date,
        "scores": [{"editorial_score": s, "active_users": u} for s, u in scores],
    }


def ids(lista):
    return [a["article_id"] for a in lista]


# ---------------------------------------------------------------------------
# normalize_title
# ---------------------------------------------------------------------------

def test_normalize_title_accenti_apostrofi_e_spazi():
    assert normalize_title("‘Oasis: Don’t Look Back”") == "oasis don t look back"
    assert normalize_title("  Perché   è  così!  ") == "perche e cosi"
    assert normalize_title("ci sar&agrave;?") == "ci sara"


# ---------------------------------------------------------------------------
# quoted_titles
# ---------------------------------------------------------------------------

def test_quoted_titles_virgoletta_di_apertura_usata_come_chiusura():
    assert quoted_titles("‘Look Back ‘di Kore-eda: la forza dei legami") == [("look back", None)]


def test_quoted_titles_apostrofo_dentro_parola_non_e_virgoletta():
    r = quoted_titles("‘Oasis: Don’t Look Back in Anger’: THIS IS NOT A DRILL!")
    assert r == [("oasis don t look back in anger", None)]


def test_quoted_titles_numero_di_stagione_dentro_le_virgolette():
    assert quoted_titles("'Black Doves 2' , il ritorno dello spionaggio Pulp") == [("black doves", 2)]


def test_quoted_titles_numero_di_stagione_dopo_la_virgoletta_di_chiusura():
    assert quoted_titles("'Black Doves' 2: svelati i nuovi volti del thriller Netflix") == [("black doves", 2)]


def test_quoted_titles_apostrofo_di_anno_abbreviato_non_e_virgoletta():
    assert quoted_titles("Oscar '27, dieci film pronti a sfidare 'Odissea'") == [("odissea", None)]


def test_quoted_titles_apostrofo_di_elisione_fuori_dalle_virgolette():
    r = quoted_titles("‘La Torta del Presidente’ di Hasan Hadi: l'odissea di Laima")
    assert r == [("la torta del presidente", None)]


def test_quoted_titles_due_titoli_e_numero_di_quattro_cifre_resta_nel_titolo():
    r = quoted_titles("'2001 Odissea' e 'Infernale Quinlan' tornano al cinema")
    assert r == [("2001 odissea", None), ("infernale quinlan", None)]


def test_quoted_titles_con_entita_html():
    assert quoted_titles("&#8216;Black Doves 3&#8217;: ci sar&agrave;?") == [("black doves", 3)]


def test_quoted_titles_senza_virgolette():
    assert quoted_titles("Il ritorno della spia che amava il Natale") == []
    assert quoted_titles("") == []


# ---------------------------------------------------------------------------
# matches_entity
# ---------------------------------------------------------------------------

def test_matches_entity_mai_per_sottostringa():
    e = {"title": "Look Back"}
    assert not matches_entity("‘Oasis: Don’t Look Back in Anger’: THIS IS NOT A DRILL!", e)
    assert matches_entity("‘Look Back’: il nuovo film di Hirokazu Kore-eda arriva al cinema", e)
    assert matches_entity("&#8216;Look Back &#8216;di Kore-eda: la forza dei legami", e)


def test_matches_entity_con_stagione():
    e = {"title": "Black Doves", "season": 2}
    assert matches_entity("'Black Doves 2' , il ritorno dello spionaggio Pulp", e)
    assert matches_entity("'Black Doves' 2: svelati i nuovi volti del thriller Netflix", e)
    # senza numero di stagione nell'articolo: corrisponde
    assert matches_entity("‘Black Doves’: Nuove informazioni sulla missione", e)
    # stagione diversa: non corrisponde
    assert not matches_entity("‘Black Doves 3’: ci sarà? Cosa sappiamo della serie Netflix", e)


def test_matches_entity_senza_stagione_nell_entita_accetta_qualunque_numero():
    e = {"title": "Black Doves"}
    assert matches_entity("‘Black Doves 3’: ci sarà? Cosa sappiamo della serie Netflix", e)


def test_matches_entity_con_alias():
    e = {
        "title": "Gli Anelli del Potere",
        "aliases": ["Il Signore degli Anelli: Gli Anelli del Potere"],
        "season": 3,
    }
    assert matches_entity("‘Gli Anelli del Potere 3’, svelato il trailer ufficiale", e)
    assert matches_entity("La terza stagione de 'Il Signore degli Anelli: gli Anelli del Potere' ...", e)
    assert not matches_entity("'Gli Anelli del Potere 2', la vera creazione richiede sacrificio", e)


def test_matches_entity_odissea_solo_tra_virgolette_e_titolo_intero():
    e = {"title": "Odissea"}
    assert matches_entity("Cast di 'Odissea': gli attori e i personaggi del film di Nolan", e)
    assert not matches_entity("'2001 Odissea' e 'Infernale Quinlan' tornano al cinema", e)
    # "l'odissea" senza virgolette non e' un titolo citato
    assert not matches_entity("Il viaggio di Ulisse e l'odissea del ritorno a casa", e)
    assert not matches_entity("‘La Torta del Presidente’ di Hasan Hadi: l'odissea di Laima", e)


# ---------------------------------------------------------------------------
# section_of / is_si_fara
# ---------------------------------------------------------------------------

def test_section_of():
    assert section_of("https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html") == "serie-tv"
    assert section_of("https://www.taxidrivers.it/561788/latest-news/si-fara/lupin-5.html") == "latest-news"
    assert section_of("https://www.taxidrivers.it/562489/review/godzilla.html") == "review"


def test_is_si_fara():
    assert is_si_fara("https://www.taxidrivers.it/561788/latest-news/si-fara/lupin-5.html")
    assert not is_si_fara("https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html")
    assert not is_si_fara("https://www.taxidrivers.it/562489/review/godzilla.html")
    # "si-fara" deve essere un segmento, non una parte di slug
    assert not is_si_fara("https://www.taxidrivers.it/562489/review/ora-si-fara-davvero.html")


# ---------------------------------------------------------------------------
# eligible_score
# ---------------------------------------------------------------------------

def test_eligible_score_soglia_di_default_quindici_utenti():
    scores = [
        {"editorial_score": 80.0, "active_users": 14},
        {"editorial_score": 60.0, "active_users": 15},
    ]
    assert eligible_score(scores) == 60.0


def test_eligible_score_massimo_tra_le_sole_settimane_valide():
    scores = [
        {"editorial_score": 90.0, "active_users": 5},
        {"editorial_score": 55.5, "active_users": 20},
        {"editorial_score": 70.2, "active_users": 40},
        {"editorial_score": 99.0, "active_users": 1},
    ]
    assert eligible_score(scores) == 70.2


def test_eligible_score_none_se_nessuna_settimana_valida():
    assert eligible_score([{"editorial_score": 72.0, "active_users": 12}]) is None


def test_eligible_score_soglia_personalizzata():
    scores = [{"editorial_score": 72.0, "active_users": 12}, {"editorial_score": 50.0, "active_users": 30}]
    assert eligible_score(scores, min_users=10) == 72.0
    assert eligible_score(scores, min_users=31) is None


def test_eligible_score_lista_vuota():
    assert eligible_score([]) is None


# ---------------------------------------------------------------------------
# choose_article: casi reali
# ---------------------------------------------------------------------------

def test_choose_article_black_doves_stagione_2():
    entity = {"title": "Black Doves", "season": 2}
    candidati = [
        cand(564645, "'Black Doves 2' , il ritorno dello spionaggio Pulp", "serie-tv", date(2026, 11, 6), [(71.6, 35)]),
        cand(564791, "‘Black Doves 3’: ci sarà? Cosa sappiamo della serie Netflix", "latest-news/si-fara",
             date(2026, 11, 7), [(65.4, 58)]),
        cand(555676, "‘Black Doves’: il trailer della seconda stagione", "trailers", date(2026, 9, 26), []),
        cand(414748, "'Black Doves': Spionaggio, Vendetta e Azione", "serie-tv", date(2024, 11, 30), []),
    ]
    c = choose_article(entity, candidati, OGGI)
    assert isinstance(c, Choice)
    assert c.article_id == 564645
    assert c.link == "https://www.taxidrivers.it/564645/serie-tv/articolo.html"
    assert c.title == "'Black Doves 2' , il ritorno dello spionaggio Pulp"
    assert c.reason == "score massimo"
    assert c.score == 71.6
    # 564791 parla della stagione 3: non e' un candidato corrispondente
    assert 564791 not in ids(c.alternatives)
    assert sorted(ids(c.alternatives)) == [414748, 555676]


def test_choose_article_look_back_esclude_oasis():
    entity = {"title": "Look Back"}
    candidati = [
        cand(551509, "‘Oasis: Don’t Look Back in Anger’: THIS IS NOT A DRILL!", "latest-news",
             date(2026, 8, 1), [(73.7, 90)]),
        cand(551853, "&#8216;Look Back &#8216;di Kore-eda: la forza dei legami", "review",
             date(2026, 9, 9), [(65.5, 40)]),
        cand(560696, "‘Look Back’: il nuovo film di Hirokazu Kore-eda arriva al cinema", "latest-news",
             date(2026, 10, 21), [(63.5, 30)]),
    ]
    c = choose_article(entity, candidati, OGGI)
    assert c.article_id == 551853
    assert c.reason == "score massimo"
    assert c.score == 65.5
    assert 551509 not in ids(c.alternatives)
    assert ids(c.alternatives) == [560696]


GODZILLA = {"title": "Godzilla Minus Zero"}


def _godzilla(utenti_549147=12, data_recensione=date(2026, 11, 13)):
    return [
        cand(549147, "‘Godzilla Minus Zero’: il trailer del sequel giapponese", "latest-news",
             date(2026, 8, 26), [(72.0, utenti_549147)]),
        cand(562014, "‘Godzilla Minus Zero’: tutto sul film di Yamazaki", "latest-news",
             date(2026, 10, 26), [(62.6, 12)]),
        cand(562489, "'Godzilla Minus Zero' – Un'occasione mancata", "review", data_recensione, []),
    ]


def test_choose_article_godzilla_recensione_recente_senza_score():
    c = choose_article(GODZILLA, _godzilla(), OGGI)
    assert c.article_id == 562489
    assert c.reason == "recensione recente senza score"
    assert c.score is None


def test_choose_article_godzilla_la_recensione_recente_vince_anche_sullo_score():
    # la regola 1 (recensione recente) viene prima della regola 2 (score)
    c = choose_article(GODZILLA, _godzilla(utenti_549147=20), OGGI)
    assert c.article_id == 562489
    assert c.reason == "recensione recente senza score"
    assert 549147 in ids(c.alternatives)


def test_choose_article_godzilla_recensione_vecchia_vince_lo_score():
    c = choose_article(GODZILLA, _godzilla(utenti_549147=20, data_recensione=date(2026, 10, 20)), OGGI)
    assert c.article_id == 549147
    assert c.reason == "score massimo"
    assert c.score == 72.0


def test_choose_article_godzilla_recensione_vecchia_e_nessuno_sopra_soglia_fallback_al_piu_recente():
    c = choose_article(GODZILLA, _godzilla(utenti_549147=12, data_recensione=date(2026, 10, 20)), OGGI)
    assert c.article_id == 562014
    assert c.reason == "nessun articolo sopra soglia: il più recente"


def test_choose_article_recensione_esattamente_a_quattordici_giorni_e_recente():
    recensione = cand(1, "'Dune' – La recensione", "review", date(2026, 11, 1), [])
    altro = cand(2, "‘Dune’: il trailer", "latest-news", date(2026, 11, 10), [(80.0, 50)])
    c = choose_article({"title": "Dune"}, [altro, recensione], OGGI)
    assert c.article_id == 1
    assert c.reason == "recensione recente senza score"
    # un giorno prima non e' piu' recente
    vecchia = cand(1, "'Dune' – La recensione", "review", date(2026, 10, 31), [])
    c2 = choose_article({"title": "Dune"}, [altro, vecchia], OGGI)
    assert c2.article_id == 2
    assert c2.reason == "score massimo"


def test_choose_article_recent_days_personalizzato():
    recensione = cand(1, "'Dune' – La recensione", "review", date(2026, 11, 10), [])
    altro = cand(2, "‘Dune’: il trailer", "latest-news", date(2026, 11, 12), [(80.0, 50)])
    c = choose_article({"title": "Dune"}, [recensione, altro], OGGI, recent_days=3)
    assert c.article_id == 2
    assert c.reason == "score massimo"


def test_choose_article_anelli_del_potere_stagione_3_con_alias():
    entity = {
        "title": "Gli Anelli del Potere",
        "aliases": ["Il Signore degli Anelli: Gli Anelli del Potere"],
        "season": 3,
    }
    candidati = [
        cand(561244, "‘Gli Anelli del Potere 3’, svelato il trailer ufficiale", "trailers",
             date(2026, 10, 23), [(59.4, 10)]),
        cand(534118, "La terza stagione de 'Il Signore degli Anelli: gli Anelli del Potere'", "latest-news",
             date(2026, 5, 17), []),
        cand(400748, "'Gli Anelli del Potere 2', la vera creazione richiede sacrificio", "serie-tv",
             date(2024, 10, 11), []),
    ]
    c = choose_article(entity, candidati, OGGI)
    assert c.article_id == 561244
    assert c.reason == "nessun articolo sopra soglia: il più recente"
    assert 400748 not in ids(c.alternatives)
    assert ids(c.alternatives) == [534118]


def test_choose_article_un_solo_candidato_va_in_fallback():
    entity = {"title": "Un cucciolo per Natale"}
    candidati = [
        cand(565040, "‘Un cucciolo per Natale’: il nuovo film Netflix", "latest-news", date(2026, 11, 8), [(31.9, 13)]),
    ]
    c = choose_article(entity, candidati, OGGI)
    assert c.article_id == 565040
    assert c.reason == "nessun articolo sopra soglia: il più recente"
    assert c.alternatives == []


def test_choose_article_odissea_non_confonde_titoli_simili():
    entity = {"title": "Odissea"}
    candidati = [
        cand(544013, "Cast di 'Odissea': gli attori e i personaggi del film di Nolan", "magazine-2",
             date(2026, 6, 1), [(83.9, 102)]),
        cand(559019, "Oscar '27, dieci film pronti a sfidare 'Odissea'", "latest-news",
             date(2026, 10, 15), [(68.3, 12)]),
        cand(557747, "'2001 Odissea' e 'Infernale Quinlan' tornano al cinema", "latest-news",
             date(2026, 10, 10), [(61.8, 12)]),
    ]
    c = choose_article(entity, candidati, OGGI)
    assert c.article_id == 544013
    assert c.reason == "score massimo"
    assert 557747 not in ids(c.alternatives)
    assert ids(c.alternatives) == [559019]


# ---------------------------------------------------------------------------
# choose_article: regole generali
# ---------------------------------------------------------------------------

def test_choose_article_nessun_candidato():
    c = choose_article({"title": "Dune"}, [], OGGI)
    assert c == Choice(None, None, None, "nessun articolo", None, [])


def test_choose_article_nessun_candidato_corrispondente():
    altri = [cand(7, "‘Lupin 5’: il trailer", "trailers", date(2026, 11, 1), [(70.0, 40)])]
    c = choose_article({"title": "Dune"}, altri, OGGI)
    assert c == Choice(None, None, None, "nessun articolo", None, [])


def test_choose_article_parita_di_score_vince_la_data_piu_recente():
    vecchio = cand(1, "‘Dune’: primo", "latest-news", date(2026, 9, 1), [(70.0, 30)])
    recente = cand(2, "‘Dune’: secondo", "latest-news", date(2026, 10, 1), [(70.0, 30)])
    for ordine in ([vecchio, recente], [recente, vecchio]):
        c = choose_article({"title": "Dune"}, ordine, OGGI)
        assert c.article_id == 2
        assert c.reason == "score massimo"


def test_choose_article_il_massimo_considera_solo_le_settimane_valide():
    a = cand(1, "‘Dune’: a", "latest-news", date(2026, 9, 1), [(95.0, 3), (50.0, 20)])
    b = cand(2, "‘Dune’: b", "latest-news", date(2026, 9, 2), [(60.0, 20)])
    c = choose_article({"title": "Dune"}, [a, b], OGGI)
    assert c.article_id == 2
    assert c.score == 60.0


def test_choose_article_fallback_a_parita_di_data_preferisce_review_poi_serie_tv():
    giorno = date(2026, 10, 1)
    news = cand(1, "‘Dune’: news", "latest-news", giorno, [])
    serie = cand(2, "‘Dune’: serie", "serie-tv", giorno, [])
    rece = cand(3, "‘Dune’: recensione", "review", giorno, [])
    c = choose_article({"title": "Dune"}, [news, serie, rece], OGGI)
    assert c.article_id == 3
    assert c.reason == "nessun articolo sopra soglia: il più recente"
    c = choose_article({"title": "Dune"}, [news, serie], OGGI)
    assert c.article_id == 2
    assert c.reason == "nessun articolo sopra soglia: il più recente"


def test_choose_article_fallback_prende_il_piu_recente():
    vecchio = cand(1, "‘Dune’: a", "review", date(2026, 9, 1), [])
    recente = cand(2, "‘Dune’: b", "latest-news", date(2026, 10, 1), [])
    c = choose_article({"title": "Dune"}, [vecchio, recente], OGGI)
    assert c.article_id == 2


def test_choose_article_alternatives_al_massimo_tre_per_score_decrescente():
    candidati = [
        cand(1, "‘Dune’: a", "latest-news", date(2026, 9, 1), [(90.0, 50)]),
        cand(2, "‘Dune’: b", "latest-news", date(2026, 9, 2), [(50.0, 50)]),
        cand(3, "‘Dune’: c", "latest-news", date(2026, 9, 3), []),
        cand(4, "‘Dune’: d", "latest-news", date(2026, 9, 4), [(70.0, 50)]),
        cand(5, "‘Dune’: e", "latest-news", date(2026, 9, 5), [(60.0, 50)]),
        cand(6, "‘Dune’: f", "latest-news", date(2026, 9, 6), [(80.0, 50)]),
    ]
    c = choose_article({"title": "Dune"}, candidati, OGGI)
    assert c.article_id == 1
    assert ids(c.alternatives) == [6, 4, 5]
    assert [a["score"] for a in c.alternatives] == [80.0, 70.0, 60.0]
    for a in c.alternatives:
        assert set(a) == {"article_id", "title", "link", "score"}


def test_choose_article_alternatives_con_none_in_fondo():
    candidati = [
        cand(1, "‘Dune’: a", "latest-news", date(2026, 9, 1), [(90.0, 50)]),
        cand(2, "‘Dune’: b", "latest-news", date(2026, 9, 2), []),
        cand(3, "‘Dune’: c", "latest-news", date(2026, 9, 3), [(50.0, 50)]),
    ]
    c = choose_article({"title": "Dune"}, candidati, OGGI)
    assert ids(c.alternatives) == [3, 2]
    assert c.alternatives[0]["score"] == 50.0
    assert c.alternatives[1]["score"] is None


def test_choose_article_non_modifica_gli_argomenti():
    entity = {"title": "Gli Anelli del Potere", "aliases": ["Il Signore degli Anelli: Gli Anelli del Potere"], "season": 3}
    candidati = [
        cand(561244, "‘Gli Anelli del Potere 3’, svelato il trailer ufficiale", "trailers", date(2026, 10, 23), [(59.4, 10)]),
        cand(534118, "La terza stagione de 'Il Signore degli Anelli: gli Anelli del Potere'", "latest-news", date(2026, 5, 17), []),
        cand(1, "‘Altro’: non corrisponde", "review", date(2026, 11, 10), []),
    ]
    entity_prima, candidati_prima = copy.deepcopy(entity), copy.deepcopy(candidati)
    choose_article(entity, candidati, OGGI)
    assert entity == entity_prima
    assert candidati == candidati_prima


# ---------------------------------------------------------------------------
# choose_si_fara
# ---------------------------------------------------------------------------

SI_FARA_TITOLO = "‘Black Doves 3’: ci sarà? Cosa sappiamo della serie Netflix"


def test_choose_si_fara_sceglie_l_articolo_si_fara_ignorando_la_stagione():
    entity = {"title": "Black Doves", "season": 2}
    candidati = [
        cand(564791, SI_FARA_TITOLO, "latest-news/si-fara", date(2026, 11, 7), [(65.4, 58)], slug="black-doves-3"),
    ]
    c = choose_si_fara(entity, candidati)
    assert c.article_id == 564791
    assert c.link == "https://www.taxidrivers.it/564791/latest-news/si-fara/black-doves-3.html"
    assert c.title == SI_FARA_TITOLO
    assert c.reason == "articolo Si farà"


def test_choose_si_fara_ignora_gli_articoli_non_si_fara_con_lo_stesso_titolo():
    entity = {"title": "Black Doves", "season": 2}
    candidati = [
        cand(564790, SI_FARA_TITOLO, "latest-news", date(2026, 11, 9), [(65.4, 58)]),
        cand(564645, "'Black Doves 2' , il ritorno dello spionaggio Pulp", "serie-tv", date(2026, 11, 6), [(71.6, 35)]),
    ]
    c = choose_si_fara(entity, candidati)
    assert c.article_id is None
    assert c.link is None
    assert c.title is None
    assert c.reason == "nessun articolo Si farà"


def test_choose_si_fara_con_titolo_diverso_non_e_scelto():
    candidati = [cand(561788, "‘Lupin 5’: la serie si farà", "latest-news/si-fara", date(2026, 11, 3), [])]
    c = choose_si_fara({"title": "Black Doves", "season": 2}, candidati)
    assert c.article_id is None
    assert c.reason == "nessun articolo Si farà"


def test_choose_si_fara_nessun_candidato():
    c = choose_si_fara({"title": "Black Doves", "season": 2}, [])
    assert c.article_id is None
    assert c.reason == "nessun articolo Si farà"


def test_choose_si_fara_piu_articoli_vince_il_piu_recente():
    entity = {"title": "Black Doves"}
    candidati = [
        cand(10, "‘Black Doves 2’: ci sarà?", "latest-news/si-fara", date(2025, 3, 1), []),
        cand(30, "‘Black Doves 3’: ci sarà?", "latest-news/si-fara", date(2026, 11, 7), []),
        cand(20, "‘Black Doves’: tornerà?", "latest-news/si-fara", date(2026, 1, 10), []),
    ]
    c = choose_si_fara(entity, candidati)
    assert c.article_id == 30
    assert c.reason == "articolo Si farà"


def test_choose_si_fara_non_modifica_gli_argomenti():
    entity = {"title": "Black Doves", "aliases": ["Colombe Nere"], "season": 2}
    candidati = [
        cand(564791, SI_FARA_TITOLO, "latest-news/si-fara", date(2026, 11, 7), [(65.4, 58)]),
        cand(564790, SI_FARA_TITOLO, "latest-news", date(2026, 11, 9), []),
    ]
    entity_prima, candidati_prima = copy.deepcopy(entity), copy.deepcopy(candidati)
    choose_si_fara(entity, candidati)
    assert entity == entity_prima
    assert candidati == candidati_prima
