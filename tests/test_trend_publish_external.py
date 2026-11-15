"""
tests/test_trend_publish_external.py

nlp/trend_publish/external_links.py: verifica di un URL esterno (verify_url,
con http_get iniettata) e scelta dei link esterni (pick_external).
Contratto in nlp/trend_publish/README.md. Niente rete, niente database.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_external.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.trend_publish.external_links import UrlCheck, pick_external, verify_url  # noqa: E402

URL = "https://www.labiennale.org/it/cinema/2026"


def _http(status=200, final_url=None, text=""):
    def http_get(url):
        return status, (final_url or url), text

    return http_get


# --------------------------------------------------------------------------
# verify_url
# --------------------------------------------------------------------------


def test_verify_ok_con_nome_nel_testo():
    chk = verify_url(URL, "Biennale Cinema", _http(text="<html>La Biennale Cinema 2026 apre...</html>"))
    assert isinstance(chk, UrlCheck)
    assert chk.ok is True
    assert chk.found_text is True
    assert chk.status == 200


def test_verify_ignora_maiuscole_e_accenti():
    chk = verify_url(URL, "Più Bello", _http(text="IL FILM PIU BELLO DELL'ANNO"))
    assert chk.ok is True and chk.found_text is True


def test_verify_nome_assente_non_e_ok():
    chk = verify_url(URL, "Black Doves", _http(text="Pagina che parla d'altro."))
    assert chk.ok is False
    assert chk.found_text is False
    assert chk.status == 200
    assert isinstance(chk.reason, str) and chk.reason.strip() != ""


def test_verify_404_non_e_ok():
    chk = verify_url(URL, "Biennale", _http(status=404, text="Biennale non trovata"))
    assert chk.ok is False
    assert chk.status == 404
    assert chk.reason.strip() != ""


def test_verify_riporta_final_url_dopo_redirect():
    finale = "https://www.labiennale.org/it/cinema/2026/programma"
    chk = verify_url(URL, "Biennale", _http(status=200, final_url=finale, text="Biennale 2026"))
    assert chk.ok is True
    assert chk.final_url == finale


def test_verify_schema_http_non_e_ok():
    url = "http://www.labiennale.org/it/cinema/2026"
    chk = verify_url(url, "Biennale", _http(text="Biennale 2026"))
    assert chk.ok is False


def test_verify_redirect_finale_su_http_non_e_ok():
    chk = verify_url(
        URL, "Biennale", _http(status=200, final_url="http://www.labiennale.org/x", text="Biennale")
    )
    assert chk.ok is False


def test_verify_eccezione_di_http_get_diventa_ko_con_messaggio():
    def http_get(url):
        raise TimeoutError("timeout")

    chk = verify_url(URL, "Biennale", http_get)
    assert chk.ok is False
    assert chk.status is None
    assert chk.found_text is False
    assert "timeout" in chk.reason


def test_verify_apostrofo_curvo_e_accenti_nel_nome_cercato():
    chk = verify_url(
        "https://it.wikipedia.org/wiki/L%27essere_amato",
        "L’essere amato",
        _http(text="Il romanzo L'essere amato è stato pubblicato nel 2024."),
    )
    assert chk.ok is True and chk.found_text is True


# --------------------------------------------------------------------------
# pick_external
# --------------------------------------------------------------------------


def _cand(url, authority, ok=True, anchor="ancora"):
    chk = UrlCheck(
        ok=ok,
        status=200 if ok else 404,
        final_url=url,
        found_text=ok,
        reason="ok" if ok else "http 404",
    )
    return {"url": url, "anchor": anchor, "authority": authority, "check": chk}


def _urls(picks):
    return [p["url"] for p in picks]


def test_pick_scarta_i_check_non_ok():
    picks, _ = pick_external(
        [
            _cand("https://www.labiennale.org/a", 90, ok=False),
            _cand("https://variety.com/b", 80),
        ]
    )
    assert _urls(picks) == ["https://variety.com/b"]


def test_pick_scarta_domini_in_blacklist_anche_con_www():
    picks, _ = pick_external(
        [
            _cand("https://www.netflix.com/title/1", 95),
            _cand("https://variety.com/b", 80),
            _cand("https://www.labiennale.org/c", 70),
        ],
        blacklist=("netflix.com",),
    )
    assert _urls(picks) == ["https://variety.com/b", "https://www.labiennale.org/c"]


def test_pick_blacklist_con_dominio_senza_www_colpisce_url_senza_www():
    picks, _ = pick_external(
        [_cand("https://netflix.com/title/1", 95), _cand("https://variety.com/b", 80)],
        blacklist=("netflix.com",),
    )
    assert _urls(picks) == ["https://variety.com/b"]


def test_pick_un_solo_link_per_dominio_tiene_authority_maggiore():
    picks, _ = pick_external(
        [
            _cand("https://variety.com/basso", 40),
            _cand("https://www.variety.com/alto", 85),
            _cand("https://www.labiennale.org/x", 60),
        ]
    )
    assert _urls(picks) == ["https://www.variety.com/alto", "https://www.labiennale.org/x"]


def test_pick_ordina_per_authority_decrescente():
    picks, _ = pick_external(
        [
            _cand("https://it.wikipedia.org/w", 50),
            _cand("https://variety.com/v", 90),
            _cand("https://www.labiennale.org/l", 70),
        ]
    )
    assert _urls(picks) == [
        "https://variety.com/v",
        "https://www.labiennale.org/l",
        "https://it.wikipedia.org/w",
    ]


def test_pick_rispetta_max_links_di_default_tre():
    picks, satisfied = pick_external(
        [
            _cand("https://variety.com/1", 90),
            _cand("https://www.labiennale.org/2", 80),
            _cand("https://it.wikipedia.org/3", 70),
            _cand("https://netflix.com/4", 60),
            _cand("https://example.org/5", 50),
        ]
    )
    assert len(picks) == 3
    assert _urls(picks) == [
        "https://variety.com/1",
        "https://www.labiennale.org/2",
        "https://it.wikipedia.org/3",
    ]
    assert satisfied is True


def test_pick_satisfied_true_con_almeno_due_validi():
    picks, satisfied = pick_external(
        [_cand("https://variety.com/1", 90), _cand("https://www.labiennale.org/2", 80)]
    )
    assert len(picks) == 2
    assert satisfied is True


def test_pick_satisfied_false_con_meno_di_due_validi_ma_ritorna_i_validi():
    picks, satisfied = pick_external(
        [
            _cand("https://variety.com/1", 90),
            _cand("https://www.labiennale.org/2", 80, ok=False),
            _cand("https://it.wikipedia.org/3", 70, ok=False),
        ]
    )
    assert _urls(picks) == ["https://variety.com/1"]
    assert satisfied is False


def test_pick_min_e_max_links_personalizzati():
    cands = [
        _cand("https://variety.com/1", 90),
        _cand("https://www.labiennale.org/2", 80),
        _cand("https://it.wikipedia.org/3", 70),
    ]
    picks, satisfied = pick_external(cands, min_links=3, max_links=4)
    assert len(picks) == 3 and satisfied is True

    picks, satisfied = pick_external(cands[:2], min_links=3, max_links=4)
    assert len(picks) == 2 and satisfied is False

    picks, satisfied = pick_external(cands, min_links=1, max_links=1)
    assert _urls(picks) == ["https://variety.com/1"]
    assert satisfied is True


def test_pick_lista_vuota():
    assert pick_external([]) == ([], False)


def test_pick_tutti_scartati_da_blacklist_o_check():
    picks, satisfied = pick_external(
        [_cand("https://netflix.com/1", 90), _cand("https://variety.com/2", 80, ok=False)],
        blacklist=("netflix.com",),
    )
    assert picks == []
    assert satisfied is False
