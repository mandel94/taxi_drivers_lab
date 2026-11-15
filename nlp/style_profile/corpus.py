"""
corpus.py

Estrae dal warehouse il corpus dell'autore (articoli "Trend Radar") diviso
per sezioni, e un campione di articoli di altri autori del sito come termine
di paragone per la stilometria.

Scrive:
- data/corpus.jsonl       una riga per sezione (article_id, split, tipo, testo)
- data/corpus_md/<id>.md  ogni articolo in Markdown, per leggerlo
- data/altri_autori.jsonl testo piano di articoli di altri autori

Uso (dalla root del progetto):
    .venv\\Scripts\\python.exe -m nlp.style_profile.corpus
"""

from __future__ import annotations

import html
import json

from data_access.db import query_df
from nlp.style_profile import config
from nlp.style_profile.parsing import sections_from_html


def load_author_articles():
    return query_df(
        """
        SELECT article_id, title, link,
               (published_at AT TIME ZONE 'Europe/Rome')::date AS published,
               content_html
        FROM articles_dim
        WHERE author_name = %(author)s AND title ~* %(pattern)s
        ORDER BY published_at
        """,
        {"author": config.AUTHOR_NAME, "pattern": config.TITLE_PATTERN},
    )


def load_other_authors():
    # Campione deterministico (ordinato per hash dell'id), stesso periodo.
    return query_df(
        """
        SELECT article_id, author_name, content_html
        FROM articles_dim
        WHERE author_name IS DISTINCT FROM %(author)s
          AND status = 'publish'
          AND published_at >= %(from)s
          AND length(content_html) > 4000
        ORDER BY md5(article_id::text)
        LIMIT %(limit)s
        """,
        {"author": config.AUTHOR_NAME, "from": config.OTHERS_FROM, "limit": config.OTHERS_SAMPLE_SIZE * 3},
    )


def load_other_headings():
    return query_df(
        """
        SELECT article_id, author_name, content_html
        FROM articles_dim
        WHERE author_name IS DISTINCT FROM %(author)s
          AND status = 'publish'
          AND published_at >= %(from)s
          AND content_html ~* '<h[2-4]'
        ORDER BY md5(article_id::text)
        LIMIT %(limit)s
        """,
        {"author": config.AUTHOR_NAME, "from": config.OTHERS_FROM, "limit": config.OTHERS_TITLES_ARTICLES},
    )


def write_other_headings() -> int:
    """Titoletti (H2-H4) di altri autori, deduplicati e con un tetto per autore."""
    from collections import Counter

    seen: set[str] = set()
    per_author: Counter = Counter()
    n = 0
    with open(config.OTHERS_TITLES_JSONL, "w", encoding="utf-8") as f:
        for _, r in load_other_headings().iterrows():
            for s in sections_from_html(r.content_html):
                if not s.heading:
                    continue
                key = " ".join(s.heading.lower().split())
                if len(key.split()) < 2 or key in seen or per_author[r.author_name] >= config.OTHERS_TITLES_PER_AUTHOR:
                    continue
                seen.add(key)
                per_author[r.author_name] += 1
                f.write(json.dumps(
                    {"article_id": int(r.article_id), "author": r.author_name,
                     "heading": s.heading, "heading_md": s.heading_md},
                    ensure_ascii=False) + "\n")
                n += 1
    return n


def article_markdown(title: str, sections) -> str:
    out = [f"# {title}", ""]
    for s in sections:
        if s.heading:
            out += [f"## {s.heading}", ""]
        out += [s.text_md, ""]
    return "\n".join(out)


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.CORPUS_MD_DIR.mkdir(parents=True, exist_ok=True)

    df = load_author_articles()
    n_rows = 0
    with open(config.CORPUS_JSONL, "w", encoding="utf-8") as f:
        for _, r in df.iterrows():
            title = html.unescape(r.title)
            sections = sections_from_html(r.content_html)
            split = "holdout" if int(r.article_id) in config.HOLDOUT_IDS else "train"
            for i, s in enumerate(sections):
                row = {
                    "article_id": int(r.article_id),
                    "published": str(r.published),
                    "title": title,
                    "link": r.link,
                    "split": split,
                    "section_index": i,
                    **s.to_dict(),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_rows += 1
            md_path = config.CORPUS_MD_DIR / f"{r.published}_{r.article_id}.md"
            md_path.write_text(article_markdown(title, sections), encoding="utf-8")
    print(f"autore: {len(df)} articoli, {n_rows} sezioni -> {config.CORPUS_JSONL}")

    others = load_other_authors()
    kept = 0
    with open(config.OTHERS_JSONL, "w", encoding="utf-8") as f:
        for _, r in others.iterrows():
            text = "\n\n".join(s.text_plain for s in sections_from_html(r.content_html))
            if len(text.split()) < config.OTHERS_MIN_WORDS:
                continue
            f.write(json.dumps({"article_id": int(r.article_id), "author": r.author_name, "text_plain": text}, ensure_ascii=False) + "\n")
            kept += 1
            if kept >= config.OTHERS_SAMPLE_SIZE:
                break
    print(f"altri autori: {kept} articoli -> {config.OTHERS_JSONL}")

    n_titles = write_other_headings()
    print(f"titoletti di altri autori: {n_titles} -> {config.OTHERS_TITLES_JSONL}")


if __name__ == "__main__":
    main()
