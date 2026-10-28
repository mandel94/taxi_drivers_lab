"""
category_mapping.py

Categoria editoriale di una pagina, dal percorso URL: porting di
td_report/map_ga4_categories.py, la stessa mappa che il report settimanale
usa per la colonna "Categoria". Il percorso e' quello GA4 (pagePath).
"""

from __future__ import annotations

CATEGORIES = {
    "News": {"latest-news", "focus-italia"},
    "Recensioni": {"review", "approfondimenti", "streaming"},
    "In Sala": {"in-sala"},
    "Cult Movies": {"cult-movie"},
    "Animazione": {"animazione", "animazione/anime"},
    "Approfondimento": {"approfondimento"},
    "Festival di Cinema": {"festival-di-cinema"},
    "Trailers": {"trailers"},
    "Serie TV": {"serie-tv", "netflix-serie-tv", "prime-video-serietv", "sky-serie-tv",
                 "disney-serietv", "paramount-serie-tv", "appletv-serietv", "tim-vision-serie-tv"},
    "Guide e Film da Vedere": {"film-da-vedere"},
    "Speciali e Magazine": {"magazine-2", "taxidrivers-magazine"},
    "Live Streaming On Demand": {"live-streaming-on-demand"},
    "Rubriche": {"rubriche"},
    "Interviste": {"interviews", "interviews-interviews"},
}


def map_category(path: str) -> str:
    """Categoria da un pagePath GA4, come nella colonna Categoria del report settimanale.

    Regole speciali: 'si-fara' vince su tutto ('Si farà'); 'serie-tv' nel percorso
    e' 'Serie TV'; 'anticipazioni' e' 'Anticipazioni'. Nel report settimanale
    'Recensioni / In Sala' viene unita a 'Recensioni', e lo stesso qui. Nessuna
    corrispondenza: 'Altro'.
    """
    category = _raw_category(path)
    return "Recensioni" if category == "Recensioni / In Sala" else category


def _raw_category(path: str) -> str:
    subpaths = str(path).split("/")

    for category, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword in subpaths:
                if "si-fara" in subpaths:
                    return "Si farà"
                if "serie-tv" in subpaths:
                    return "Serie TV"
                if "anticipazioni" in subpaths:
                    return "Anticipazioni"
                if category == "Recensioni" and "in-sala" in subpaths:
                    return "Recensioni / In Sala"
                if category == "Trailers" and "in-sala" in subpaths:
                    return "Trailers / In Sala"
                return category

    if "si-fara" in subpaths:
        return "Si farà"
    if "anticipazioni" in subpaths:
        return "Anticipazioni"
    return "Altro"
