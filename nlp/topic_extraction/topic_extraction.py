"""
topic_extraction.py

Modulo di preprocessing testuale per il task di topic extraction sugli
articoli di taxidrivers.it.

Copre le prime due fasi della pipeline concordata:
    1. Pulizia dell'HTML (rimozione tag, shortcode WP, normalizzazione spazi)
    2. Preprocessing NLP in italiano con spaCy (lemmatizzazione filtrata per
       POS, estrazione entità nominate)

L'output è pensato per alimentare lo step successivo (l'estrazione dei topic
vera e propria, via KeyBERT o classificazione LLM, ancora da implementare):
la colonna `lemmas_joined` è già pronta per essere passata a TF-IDF/KeyBERT.

Dipendenze:
    pip install pandas beautifulsoup4 lxml spacy
    python -m spacy download it_core_news_lg

Uso tipico:
    from topic_extraction import preprocess_articles

    result_df = preprocess_articles(df)  # df: article_id, content
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Pulizia HTML
# ---------------------------------------------------------------------------

# Tag il cui contenuto va scartato: non portano segnale testuale utile
_TAGS_TO_DROP = ("script", "style", "noscript", "iframe")

# Shortcode WordPress residui dopo il parsing (es. [caption ...][/caption])
_SHORTCODE_RE = re.compile(r"\[/?\w[^\]]*\]")
_MULTI_WHITESPACE_RE = re.compile(r"\s+")


def clean_html(raw: str | None) -> str:
    """
    Converte un blocco di content HTML in testo piano normalizzato.

    Gestisce con grazia anche input già testuali (senza tag) o vuoti/None,
    dato che il campo `content` del DataFrame non è garantito essere sempre
    HTML.
    """
    if not raw or not isinstance(raw, str):
        return ""

    try:
        soup = BeautifulSoup(raw, "lxml")
    except Exception:
        # lxml non disponibile o parsing fallito: fallback al parser built-in
        soup = BeautifulSoup(raw, "html.parser")

    for tag_name in _TAGS_TO_DROP:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    text = soup.get_text(separator=" ")
    text = _SHORTCODE_RE.sub(" ", text)
    text = _MULTI_WHITESPACE_RE.sub(" ", text).strip()

    return text


# ---------------------------------------------------------------------------
# 2. Preprocessing NLP (spaCy, italiano)
# ---------------------------------------------------------------------------

@dataclass
class PreprocessConfig:
    """Parametri configurabili della fase di preprocessing NLP."""

    model_name: str = "it_core_news_lg"
    disable: tuple[str, ...] = ("parser",)
    allowed_pos: frozenset[str] = field(
        default_factory=lambda: frozenset({"NOUN", "PROPN", "ADJ"})
    )
    entity_labels: frozenset[str] = field(
        default_factory=lambda: frozenset({"PER", "ORG", "LOC", "MISC"})
    )
    min_token_len: int = 3
    batch_size: int = 50
    n_process: int = 1


@lru_cache(maxsize=4)
def _load_nlp(model_name: str, disable: tuple[str, ...]):
    """Carica (e mette in cache) la pipeline spaCy richiesta.
    Se il modello non è installato, tenta il download automatico.
    """
    import sys
    import subprocess
    import spacy

    try:
        logger.info("Tentativo di caricamento modello spaCy '%s' (disable=%s)", model_name, disable)
        return spacy.load(model_name, disable=list(disable))
    except OSError:
        logger.warning("Modello '%s' non trovato. Tento il download automatico...", model_name)
        try:
            # Esegue il download usando lo stesso interprete Python corrente (funziona anche in venv)
            subprocess.run(
                [sys.executable, "-m", "spacy", "download", model_name],
                check=True
            )
            # Riprova il caricamento dopo il download successo
            logger.info("Download completato. Riprovo il caricamento di '%s'...", model_name)
            return spacy.load(model_name, disable=list(disable))
        except subprocess.CalledProcessError as e:
            logger.error("Errore critico durante il download del modello spaCy: %s", e)
            raise RuntimeError(
                f"Impossibile scaricare il modello '{model_name}'. "
                f"Esegui manualmente: python -m spacy download {model_name}"
            ) from e


def _extract_lemmas(doc, config: PreprocessConfig) -> list[str]:
    """Lemmi normalizzati (minuscolo), filtrati per POS, stopword e lunghezza."""
    lemmas = []
    for token in doc:
        if not token.is_alpha or token.is_stop:
            continue
        if token.pos_ not in config.allowed_pos:
            continue
        lemma = token.lemma_.lower().strip()
        if len(lemma) >= config.min_token_len:
            lemmas.append(lemma)
    return lemmas


def _extract_entities(doc, config: PreprocessConfig) -> list[tuple[str, str]]:
    """Entità nominate uniche (case-insensitive), nella forma (testo, label)."""
    seen_keys: set[str] = set()
    entities: list[tuple[str, str]] = []
    for ent in doc.ents:
        if ent.label_ not in config.entity_labels:
            continue
        key = ent.text.strip().lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        entities.append((ent.text.strip(), ent.label_))
    return entities


# ---------------------------------------------------------------------------
# 3. Orchestrazione: DataFrame in, DataFrame preprocessato out
# ---------------------------------------------------------------------------

def ner_task(
    df: pd.DataFrame,
    content_col: str = "content",
    id_col: str = "article_id",
    config: PreprocessConfig | None = None,
) -> pd.DataFrame:
    """
    Pulisce e preprocessa il contenuto degli articoli, pronto per l'estrazione
    dei topic vera e propria (TF-IDF / KeyBERT / classificazione LLM a valle).

    Parametri
    ---------
    df : DataFrame con almeno le colonne `id_col` e `content_col`.
    content_col : nome della colonna col contenuto (tendenzialmente HTML).
    id_col : nome della colonna identificativa dell'articolo.
    config : parametri di preprocessing; se None usa i default.

    Ritorna
    -------
    DataFrame con colonne:
        article_id, clean_text, n_tokens, lemmas, lemmas_joined, entities
    `lemmas_joined` è pronto per essere passato direttamente a TF-IDF/KeyBERT.
    """
    if content_col not in df.columns or id_col not in df.columns:
        raise ValueError(
            f"Il DataFrame deve contenere le colonne '{id_col}' e '{content_col}'"
        )

    config = config or PreprocessConfig()

    working = df[[id_col, content_col]].copy()
    working["clean_text"] = working[content_col].apply(clean_html)

    n_empty = int((working["clean_text"] == "").sum())
    if n_empty:
        logger.warning("%d articoli con testo vuoto dopo la pulizia HTML", n_empty)

    nlp = _load_nlp(config.model_name, config.disable)

    texts = working["clean_text"].tolist()
    docs = nlp.pipe(texts, batch_size=config.batch_size, n_process=config.n_process)

    lemmas_col: list[list[str]] = []
    entities_col: list[list[tuple[str, str]]] = []

    for i, doc in enumerate(docs, start=1):
        lemmas_col.append(_extract_lemmas(doc, config))
        entities_col.append(_extract_entities(doc, config))
        if i % 500 == 0:
            logger.info("Preprocessati %d/%d articoli", i, len(texts))

    result = pd.DataFrame({
        id_col: working[id_col].values,
        "clean_text": working["clean_text"].values,
        "n_tokens": [len(l) for l in lemmas_col],
        "lemmas": lemmas_col,
        "lemmas_joined": [" ".join(l) for l in lemmas_col],
        "entities": entities_col,
    })

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    demo_df = pd.DataFrame({
        "article_id": [1, 2],
        "content": [
            "<p>Il nuovo film di <strong>Alice Rohrwacher</strong> racconta una storia "
            "di formazione ambientata in Umbria, tra realismo magico e critica sociale.</p>",
            "<div>Serie TV: la seconda stagione conferma il tono thriller e amplia "
            "il cast con nuovi personaggi legati alla mafia calabrese.</div>",
        ],
    })

    out = ner_task(demo_df)
    print(out[["article_id", "n_tokens", "lemmas_joined", "entities"]])