"""
config.py

Costanti condivise del profilo di stile (imitazione dello stile d'autore).

Il corpus sono gli articoli "Trend Radar" di Manuel De Luzi, gli unici che
firma sul sito. Una parte resta fuori dalla costruzione del profilo
(hold-out): serve solo a verificare, nel giro "genera, confronta, correggi",
che il profilo funzioni su testi che non ha visto.
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CORPUS_JSONL = DATA_DIR / "corpus.jsonl"
CORPUS_MD_DIR = DATA_DIR / "corpus_md"
OTHERS_JSONL = DATA_DIR / "altri_autori.jsonl"
OTHERS_TITLES_JSONL = DATA_DIR / "altri_titoli.jsonl"
TARGETS_YAML = BASE_DIR / "metriche_target.yaml"
TITLES_TARGETS_YAML = BASE_DIR / "metriche_titoli.yaml"
DIVIETI_YAML = BASE_DIR / "divieti.yaml"
PROFILE_MD = BASE_DIR / "profilo_stile.md"
CHECKS_DIR = BASE_DIR / "giri"

AUTHOR_NAME = "Manuel De Luzi"
TITLE_PATTERN = r"trend[\s\-]?radar"

# Articoli tenuti fuori dal profilo: uno di settembre (senza "Prima di
# lasciarci") e due recenti (con), cosi' il controllo copre entrambi i formati.
HOLDOUT_IDS = frozenset({552807, 561483, 565041})

# Tipi di sezione riconosciuti nel corpus e nei testi da controllare.
SECTION_TYPES = ("intro", "corpo", "spunti", "prima_di_lasciarci", "sguardo")

# Campione di articoli di altri autori del sito: fa da termine di paragone
# per la distanza stilometrica (deve risultare piu' lontano dei tuoi testi).
OTHERS_SAMPLE_SIZE = 60
OTHERS_MIN_WORDS = 600
OTHERS_FROM = "2026-01-01"

# Titoletti degli altri autori: termine di paragone per i titoli di sezione.
# Si tengono titoletti di almeno 2 parole, senza doppioni, al massimo
# OTHERS_TITLES_PER_AUTHOR per autore (due o tre autori scrivono meta' dei titoletti del sito).
OTHERS_TITLES_ARTICLES = 600
OTHERS_TITLES_PER_AUTHOR = 25

# Dal numero del 25/07 i titoletti hanno la forma "Ancora, lettura". Il primo
# numero (21/07, 543674) ha titoletti generici di categoria e resta fuori dagli
# intervalli dei titoli.
TITLES_FROM_DATE = "2026-07-22"

# Da fine settembre quasi tutte le sezioni tematiche hanno per titolo il nome
# dell'opera ("*Titolo*, lettura"); prima prevalevano le intestazioni di
# categoria ("Film in sala, ..."). Il formato attuale si misura da qui.
TITLES_RECENT_FROM = "2026-09-26"

SPACY_MODEL = "it_core_news_lg"
