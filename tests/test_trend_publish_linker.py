"""
tests/test_trend_publish_linker.py

Fase 2 di nlp/trend_publish: link interni, corsivo dei titoli e link esterni
sul Draft del Trend Radar (nlp/trend_publish/linker.py, con Section e Draft di
doc.py). I Draft dei test si costruiscono a mano, senza passare dal parser.
Non servono database ne' rete.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_linker.py
"""

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.trend_publish.doc import Draft, Section  # noqa: E402
from nlp.trend_publish.linker import (  # noqa: E402
    LinkSpec,
    apply_external_links,
    apply_internal_links,
    italicize_titles,
)

# Il contratto non fissa la reason per un url gia' usato da una spec precedente:
# si verifica solo che contenga questa sottostringa (es. "url gia' usato").
SOTTOSTRINGA_URL_USATO = "usato"

URL_BD = "https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html"


def sec(kind, title=None, paragraphs=(), items=()):
    return Section(kind=kind, title=title, paragraphs=list(paragraphs), items=list(items))


def draft(*sections):
    return Draft(sections=list(sections))


def snapshot(d):
    return [(s.kind, s.title, list(s.paragraphs), list(s.items)) for s in d.sections]


def base_draft():
    """Indici sezione: 0 intro, 1 section, 2 pdl, 3 sguardo."""
    return draft(
        sec("intro", None, ["Questa settimana parliamo di Black Doves e di molto altro."]),
        sec(
            "section",
            "Black Doves, quando lo spy thriller si unisce al dramma famigliare",
            [
                "Su Netflix arriva Black Doves, con Keira Knightley. "
                "Black Doves racconta la storia di una spia.",
                "Anche in Black Doves la famiglia conta piu' del resto.",
            ],
        ),
        sec(
            "pdl",
            "Prima di lasciarci",
            items=[
                "Recuperate Black Doves, ne vale la pena.",
                "Black Doves e' la scelta della settimana.",
            ],
        ),
        sec("sguardo", "Uno sguardo d'insieme", ["Black Doves ha dominato la settimana."]),
    )


# --------------------------------------------------------------------------
# apply_internal_links
# --------------------------------------------------------------------------

def test_link_interno_solo_sulla_prima_occorrenza_del_primo_paragrafo_di_sezione():
    new, report = apply_internal_links(base_draft(), [LinkSpec("Black Doves", URL_BD)])

    atteso = base_draft()
    atteso.sections[1].paragraphs[0] = (
        f"Su Netflix arriva [***Black Doves***]({URL_BD}), con Keira Knightley. "
        "Black Doves racconta la storia di una spia."
    )
    assert snapshot(new) == snapshot(atteso)
    # il titolo non e' toccato
    assert new.sections[1].title == "Black Doves, quando lo spy thriller si unisce al dramma famigliare"

    assert len(report) == 1
    assert report[0]["surface"] == "Black Doves"
    assert report[0]["url"] == URL_BD
    assert report[0]["applied"] is True
    assert report[0]["where"] == "1/0"


def test_link_interno_scope_pdl_va_sul_primo_item_e_non_nei_paragrafi():
    new, report = apply_internal_links(base_draft(), [LinkSpec("Black Doves", URL_BD, scope="pdl")])

    atteso = base_draft()
    atteso.sections[2].items[0] = f"Recuperate [***Black Doves***]({URL_BD}), ne vale la pena."
    assert snapshot(new) == snapshot(atteso)
    assert report[0]["applied"] is True
    assert report[0]["where"] == "2/0"


def test_link_interno_scope_any_include_intro_ma_mai_il_titolo():
    new, report = apply_internal_links(base_draft(), [LinkSpec("Black Doves", URL_BD, scope="any")])

    atteso = base_draft()
    atteso.sections[0].paragraphs[0] = (
        f"Questa settimana parliamo di [***Black Doves***]({URL_BD}) e di molto altro."
    )
    assert snapshot(new) == snapshot(atteso)
    assert report[0]["applied"] is True
    assert report[0]["where"] == "0/0"


def test_link_interno_scope_any_arriva_allo_sguardo_ma_non_al_titolo():
    d = draft(
        sec("intro", None, ["Niente da dire qui."]),
        sec("section", "Dune, il ritorno", ["Niente neppure qui."]),
        sec("sguardo", "Uno sguardo d'insieme", ["Il pubblico cerca Dune ovunque."]),
    )
    url = "https://www.taxidrivers.it/7/film/dune.html"
    new, report = apply_internal_links(d, [LinkSpec("Dune", url, scope="any")])

    assert new.sections[1].title == "Dune, il ritorno"
    assert new.sections[2].paragraphs == [f"Il pubblico cerca [***Dune***]({url}) ovunque."]
    assert report[0]["applied"] is True
    assert report[0]["where"] == "2/0"


def test_link_interno_scope_body_non_cerca_in_titolo_intro_e_sguardo():
    d = draft(
        sec("intro", None, ["Niente da dire qui."]),
        sec("section", "Dune, il ritorno", ["Niente neppure qui."]),
        sec("sguardo", "Uno sguardo d'insieme", ["Il pubblico cerca Dune ovunque."]),
    )
    prima = snapshot(d)
    new, report = apply_internal_links(d, [LinkSpec("Dune", "https://www.taxidrivers.it/7/film/dune.html")])

    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["where"] is None
    assert report[0]["reason"] == "surface assente"


def test_link_interno_stesso_url_per_due_spec_scarta_la_seconda():
    specs = [
        LinkSpec("Black Doves", URL_BD),
        LinkSpec("Keira Knightley", URL_BD),  # surface presente nel testo: il rifiuto e' per l'url
    ]
    new, report = apply_internal_links(base_draft(), specs)

    assert [r["applied"] for r in report] == [True, False]
    assert SOTTOSTRINGA_URL_USATO in report[1]["reason"]
    assert report[1]["where"] is None
    assert "Keira Knightley" in new.sections[1].paragraphs[0]
    assert "[***Keira Knightley***]" not in new.sections[1].paragraphs[0]


def test_link_interno_surface_assente():
    prima = snapshot(base_draft())
    new, report = apply_internal_links(
        base_draft(), [LinkSpec("Titolo Inesistente", "https://www.taxidrivers.it/9/x.html")]
    )
    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["where"] is None
    assert report[0]["reason"] == "surface assente"


def test_link_interno_salta_occorrenza_gia_dentro_un_link_e_usa_la_successiva():
    vecchio = "https://www.taxidrivers.it/1/old.html"
    d = draft(
        sec("intro", None, ["Intro senza titoli."]),
        sec(
            "section",
            "Un titolo",
            [
                f"Leggi [***Black Doves***]({vecchio}) ora.",
                "Poi Black Doves torna.",
            ],
        ),
    )
    new, report = apply_internal_links(d, [LinkSpec("Black Doves", URL_BD)])

    assert new.sections[1].paragraphs == [
        f"Leggi [***Black Doves***]({vecchio}) ora.",
        f"Poi [***Black Doves***]({URL_BD}) torna.",
    ]
    assert report[0]["applied"] is True
    assert report[0]["where"] == "1/1"


def test_link_interno_occorrenza_unica_gia_in_un_link_non_si_applica():
    vecchio = "https://www.taxidrivers.it/1/old.html"
    d = draft(
        sec("intro", None, ["Intro senza titoli."]),
        sec("section", "Un titolo", [f"Leggi [***Black Doves***]({vecchio}) ora."]),
    )
    prima = snapshot(d)
    new, report = apply_internal_links(d, [LinkSpec("Black Doves", URL_BD)])

    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["where"] is None
    assert report[0]["reason"]


def _draft_godzilla():
    return draft(
        sec("intro", None, ["Intro senza titoli."]),
        sec("section", "Il ritorno del mostro", ["Godzilla Minus Zero ha vinto un Oscar."]),
        sec("section", "Il precedente", ["Prima c'era Godzilla Minus One, molto amato."]),
    )


def test_link_interno_due_spec_con_surface_simili_in_sezioni_diverse():
    url_zero = "https://www.taxidrivers.it/100/film/godzilla-minus-zero.html"
    url_one = "https://www.taxidrivers.it/101/film/godzilla-minus-one.html"
    specs = [LinkSpec("Godzilla Minus Zero", url_zero), LinkSpec("Godzilla Minus One", url_one)]
    atteso = [
        ("intro", None, ["Intro senza titoli."], []),
        ("section", "Il ritorno del mostro",
         [f"[***Godzilla Minus Zero***]({url_zero}) ha vinto un Oscar."], []),
        ("section", "Il precedente",
         [f"Prima c'era [***Godzilla Minus One***]({url_one}), molto amato."], []),
    ]

    new, report = apply_internal_links(_draft_godzilla(), specs)
    assert snapshot(new) == atteso
    assert [r["where"] for r in report] == ["1/0", "2/0"]
    assert all(r["applied"] for r in report)

    # l'ordine delle spec non cambia il risultato
    new_inv, _ = apply_internal_links(_draft_godzilla(), list(reversed(specs)))
    assert snapshot(new_inv) == atteso


def test_link_interno_surface_contenuta_in_un_altra_non_annida_i_link():
    url_dune = "https://www.taxidrivers.it/200/film/dune.html"
    url_due = "https://www.taxidrivers.it/201/film/dune-parte-due.html"
    d = draft(
        sec("intro", None, ["Intro senza titoli."]),
        sec("section", "Il sequel", ["Dune: Parte Due ha incassato molto."]),
        sec("section", "Il primo", ["Il primo Dune resta un classico."]),
    )
    # prima la surface piu' lunga: l'occorrenza dentro il suo link viene saltata
    specs = [LinkSpec("Dune: Parte Due", url_due), LinkSpec("Dune", url_dune)]
    new, report = apply_internal_links(d, specs)

    assert new.sections[1].paragraphs == [f"[***Dune: Parte Due***]({url_due}) ha incassato molto."]
    assert new.sections[2].paragraphs == [f"Il primo [***Dune***]({url_dune}) resta un classico."]
    assert [r["where"] for r in report] == ["1/0", "2/0"]


def test_link_interno_caso_reale_titolo_con_due_punti_linkato_per_intero():
    surface = "Il Signore degli Anelli: Gli Anelli del Potere"
    url = "https://www.taxidrivers.it/300/serie-tv/gli-anelli-del-potere.html"
    d = draft(
        sec("intro", None, ["Intro senza titoli."]),
        sec("section", "Il fantasy torna", [f"Si parla della terza stagione de {surface}."]),
    )
    new, report = apply_internal_links(d, [LinkSpec(surface, url)])

    assert new.sections[1].paragraphs == [
        f"Si parla della terza stagione de [***{surface}***]({url})."
    ]
    assert report[0]["applied"] is True
    assert report[0]["where"] == "1/0"


def test_link_interno_funzione_pura_non_modifica_il_draft_in_input():
    d = base_draft()
    copia = copy.deepcopy(d)
    apply_internal_links(d, [LinkSpec("Black Doves", URL_BD), LinkSpec("Black Doves", URL_BD, scope="pdl")])
    assert d == copia


def test_link_interno_con_elenco_spec_vuoto():
    d = base_draft()
    new, report = apply_internal_links(d, [])
    assert snapshot(new) == snapshot(base_draft())
    assert report == []


# --------------------------------------------------------------------------
# italicize_titles
# --------------------------------------------------------------------------

def _draft_corsivi():
    return draft(
        sec("intro", None, ["Parliamo di Black Doves e Godzilla Minus One."]),
        sec(
            "section",
            "Black Doves, il ritorno",
            [
                f"[***Black Doves***]({URL_BD}) e Godzilla Minus Zero.",
                "Qui *Black Doves* resta e Black Doves no.",
            ],
        ),
        sec("pdl", "Prima di lasciarci", items=["Guardate Godzilla Minus Zero."]),
        sec("sguardo", "Uno sguardo d'insieme", ["Black Doves vince."]),
    )


def test_italicize_titles_su_ogni_sezione_titoli_compresi():
    surfaces = ["Black Doves", "Godzilla Minus Zero", "Godzilla Minus One"]
    new = italicize_titles(_draft_corsivi(), surfaces)

    atteso = [
        ("intro", None, ["Parliamo di *Black Doves* e *Godzilla Minus One*."], []),
        ("section", "*Black Doves*, il ritorno",
         [
             f"[***Black Doves***]({URL_BD}) e *Godzilla Minus Zero*.",
             "Qui *Black Doves* resta e *Black Doves* no.",
         ], []),
        ("pdl", "Prima di lasciarci", [], ["Guardate *Godzilla Minus Zero*."]),
        ("sguardo", "Uno sguardo d'insieme", ["*Black Doves* vince."], []),
    ]
    assert snapshot(new) == atteso


def test_italicize_titles_non_trasforma_corsivo_esistente_ne_annida():
    d = draft(sec("section", "Titolo", ["Qui *Black Doves* resta."]))
    new = italicize_titles(d, ["Black Doves"])
    par = new.sections[0].paragraphs[0]
    assert par == "Qui *Black Doves* resta."
    assert "**" not in par


def test_italicize_titles_lascia_le_occorrenze_dentro_i_link_com_erano():
    d = draft(sec("section", "Titolo", [f"Vedi [***Black Doves***]({URL_BD}) subito."]))
    new = italicize_titles(d, ["Black Doves"])
    assert new.sections[0].paragraphs == [f"Vedi [***Black Doves***]({URL_BD}) subito."]


def test_italicize_titles_surface_piu_lunga_per_prima_senza_corsivi_annidati():
    lunga = "Il Signore degli Anelli: Gli Anelli del Potere"
    corta = "Gli Anelli del Potere"
    testo = f"La serie {lunga} torna. Ma {corta} da soli?"
    atteso = f"La serie *{lunga}* torna. Ma *{corta}* da soli?"

    for ordine in ([corta, lunga], [lunga, corta]):
        d = draft(sec("section", "Titolo", [testo]))
        new = italicize_titles(d, ordine)
        par = new.sections[0].paragraphs[0]
        assert par == atteso
        assert "**" not in par
        assert "*Il Signore degli Anelli: *" not in par


def test_italicize_titles_funzione_pura():
    d = _draft_corsivi()
    copia = copy.deepcopy(d)
    italicize_titles(d, ["Black Doves", "Godzilla Minus Zero"])
    assert d == copia


# --------------------------------------------------------------------------
# apply_external_links
# --------------------------------------------------------------------------

URL_NETFLIX = "https://www.netflix.com/it/"
URL_APPLE = "https://www.apple.com/it/tv/"


def _draft_esterni():
    """Indici sezione: 0 intro, 1 section, 2 pdl, 3 sguardo."""
    return draft(
        sec("intro", None, ["Questa settimana parliamo di Netflix e di altro."]),
        sec(
            "section",
            "Netflix e il resto del mondo",
            [
                "Lo ha annunciato Netflix ieri sera.",
                "Apple TV+ risponde con una nuova serie.",
            ],
        ),
        sec("pdl", "Prima di lasciarci", items=["Guardate Sky stasera."]),
        sec("sguardo", "Uno sguardo d'insieme", ["Sky e Netflix chiudono la settimana."]),
    )


def test_link_esterno_ancora_unica_nei_paragrafi_di_sezione():
    new, report = apply_external_links(_draft_esterni(), [{"anchor": "Netflix", "url": URL_NETFLIX}])

    atteso = _draft_esterni()
    atteso.sections[1].paragraphs[0] = f"Lo ha annunciato [Netflix]({URL_NETFLIX}) ieri sera."
    # intro, titolo, pdl e sguardo (che contengono "Netflix") restano com'erano
    assert snapshot(new) == snapshot(atteso)
    assert "rel=" not in new.sections[1].paragraphs[0]
    assert "target" not in new.sections[1].paragraphs[0]
    assert report[0]["applied"] is True
    assert report[0]["where"] == "1/0"


def test_link_esterno_ancora_che_compare_due_volte_e_ambigua():
    d = draft(
        sec("intro", None, ["Intro."]),
        sec("section", "Titolo", ["Netflix ha detto la sua.", "Poi Netflix ha confermato."]),
    )
    prima = snapshot(d)
    new, report = apply_external_links(d, [{"anchor": "Netflix", "url": URL_NETFLIX}])

    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["reason"] == "ancora ambigua"


def test_link_esterno_due_volte_nello_stesso_paragrafo_e_ambigua():
    d = draft(
        sec("intro", None, ["Intro."]),
        sec("section", "Titolo", ["Netflix ha detto. Netflix ha confermato."]),
    )
    prima = snapshot(d)
    new, report = apply_external_links(d, [{"anchor": "Netflix", "url": URL_NETFLIX}])
    assert snapshot(new) == prima
    assert report[0]["reason"] == "ancora ambigua"


def test_link_esterno_ancora_assente():
    prima = snapshot(_draft_esterni())
    new, report = apply_external_links(_draft_esterni(), [{"anchor": "HBO Max", "url": "https://www.hbomax.com/it/"}])
    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["reason"] == "ancora assente"


def test_link_esterno_ancora_solo_nel_titolo_o_nell_intro_e_assente():
    prima = snapshot(_draft_esterni())
    picks = [
        {"anchor": "mondo", "url": "https://example.org/mondo"},            # solo titolo
        {"anchor": "Questa settimana", "url": "https://example.org/sett"},  # solo intro
    ]
    new, report = apply_external_links(_draft_esterni(), picks)
    assert snapshot(new) == prima
    assert [r["applied"] for r in report] == [False, False]
    assert [r["reason"] for r in report] == ["ancora assente", "ancora assente"]


def test_link_esterno_ancora_solo_in_pdl_o_sguardo_e_assente():
    prima = snapshot(_draft_esterni())
    new, report = apply_external_links(_draft_esterni(), [{"anchor": "Sky", "url": "https://www.sky.it/"}])
    assert snapshot(new) == prima
    assert report[0]["applied"] is False
    assert report[0]["reason"] == "ancora assente"


def test_link_esterno_ancora_gia_dentro_un_link_non_si_applica():
    d = draft(
        sec("intro", None, ["Intro."]),
        sec("section", "Titolo", ["Vedi [Netflix](https://www.netflix.com/old) qui."]),
    )
    prima = snapshot(d)
    new, report = apply_external_links(d, [{"anchor": "Netflix", "url": URL_NETFLIX}])
    assert snapshot(new) == prima
    assert report[0]["applied"] is False


def test_link_esterno_conta_solo_le_occorrenze_fuori_dai_link():
    d = draft(
        sec("intro", None, ["Intro."]),
        sec("section", "Titolo", [
            "Vedi [Netflix](https://www.netflix.com/old) qui.",
            "Poi Netflix annuncia.",
        ]),
    )
    new, report = apply_external_links(d, [{"anchor": "Netflix", "url": URL_NETFLIX}])
    assert new.sections[1].paragraphs == [
        "Vedi [Netflix](https://www.netflix.com/old) qui.",
        f"Poi [Netflix]({URL_NETFLIX}) annuncia.",
    ]
    assert report[0]["applied"] is True
    assert report[0]["where"] == "1/1"


def test_link_esterno_piu_picks_coerenti_con_rapporto():
    picks = [
        {"anchor": "Netflix", "url": URL_NETFLIX},
        {"anchor": "Apple TV+", "url": URL_APPLE},
    ]
    new, report = apply_external_links(_draft_esterni(), picks)

    assert new.sections[1].paragraphs == [
        f"Lo ha annunciato [Netflix]({URL_NETFLIX}) ieri sera.",
        f"[Apple TV+]({URL_APPLE}) risponde con una nuova serie.",
    ]
    assert [r["applied"] for r in report] == [True, True]
    assert [r["where"] for r in report] == ["1/0", "1/1"]


def test_link_esterno_picks_misti_applicata_e_non_applicata():
    picks = [
        {"anchor": "Netflix", "url": URL_NETFLIX},
        {"anchor": "HBO Max", "url": "https://www.hbomax.com/it/"},
    ]
    new, report = apply_external_links(_draft_esterni(), picks)
    assert f"[Netflix]({URL_NETFLIX})" in new.sections[1].paragraphs[0]
    assert [r["applied"] for r in report] == [True, False]
    assert report[1]["reason"] == "ancora assente"
    assert report[1]["where"] is None


def test_link_esterno_funzione_pura():
    d = _draft_esterni()
    copia = copy.deepcopy(d)
    picks = [{"anchor": "Netflix", "url": URL_NETFLIX}, {"anchor": "HBO Max", "url": "https://x.example/"}]
    picks_copia = copy.deepcopy(picks)
    apply_external_links(d, picks)
    assert d == copia
    assert picks == picks_copia
