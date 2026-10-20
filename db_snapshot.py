"""
db_snapshot.py

Fotografia read-only del database Postgres del progetto: entita' presenti
(tabelle, viste, colonne, indici, vincoli, chiavi esterne), quantita' di
dati per tabella e statistiche essenziali sulle colonne. Serve a rispondere
in una sola occhiata a "cosa c'e' dentro il DB" senza aprire psql.

Uso:
    python db_snapshot.py                 # report testuale su stdout
    python db_snapshot.py --json          # JSON machine-readable
    python db_snapshot.py --md            # Markdown
    python db_snapshot.py --schema-only   # solo struttura, nessun dato
    python db_snapshot.py --fast          # conteggi stimati dal catalogo
    python db_snapshot.py --sample 5      # righe di esempio per tabella

La connessione usa DATABASE_URL oppure le variabili POSTGRES_* lette da .env,
con la stessa priorita' di alembic/env.py. La sessione e' aperta in sola
lettura: nessuna scrittura viene eseguita.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

TOP_N = 10
SAMPLE_VALUE_MAX = 70
TEXT_COLUMN_TOPN_MAX_DISTINCT = 25
STATS_ROW_SOFT_LIMIT = 500_000
EXCLUDED_RELATIONS = ("alembic_version",)

_DELETE_ACTIONS = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}


# ---------------------------------------------------------------------------
# Connessione
# ---------------------------------------------------------------------------


def build_database_url(explicit: str | None = None) -> str:
    """Costruisce la DSN psycopg2, con la stessa priorita' di alembic/env.py."""
    if explicit:
        return _to_psycopg_url(explicit)
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if url:
        return _to_psycopg_url(url)
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5434")
    db = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _to_psycopg_url(url: str) -> str:
    """Rimuove il suffisso driver SQLAlchemy (+psycopg2) se presente."""
    return url.replace("postgresql+psycopg2://", "postgresql://")


# ---------------------------------------------------------------------------
# Strutture dati
# ---------------------------------------------------------------------------


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    default: str | None = None
    is_primary_key: bool = False
    fk_target: str | None = None
    null_count: int | None = None
    distinct_count: int | None = None
    min_value: str | None = None
    max_value: str | None = None
    avg_value: float | None = None
    sum_value: float | None = None
    true_count: int | None = None
    top_values: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    name: str
    column: str
    ref_table: str
    ref_column: str
    on_delete: str


@dataclass
class IndexInfo:
    name: str
    definition: str
    unique: bool


@dataclass
class RelationInfo:
    name: str
    schema: str
    kind: str
    comment: str | None
    is_legacy: bool
    rows_exact: int | None = None
    rows_estimated: int | None = None
    size_bytes: int | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    sample: list[dict[str, Any]] = field(default_factory=list)
    stats_skipped: bool = False


@dataclass
class Snapshot:
    snapshot_at: str
    server_version: str
    host: str
    port: str
    database: str
    size_bytes: int
    alembic_revision: str | None
    tables: list[RelationInfo] = field(default_factory=list)
    views: list[RelationInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper SQL
# ---------------------------------------------------------------------------


def _q(ident: str) -> str:
    """Quoting sicuro di un identificatore Postgres."""
    return '"' + ident.replace('"', '""') + '"'


def _typed(rel: str) -> str:
    return f'public.{_q(rel)}'


def _fetch(cur, sql: str, params: Iterable[Any] = ()) -> list[dict]:
    cur.execute(sql, tuple(params))
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_database_info(conn, cur) -> dict:
    cur.execute("SELECT version()")
    server_version = cur.fetchone()["version"]
    cur.execute("SELECT current_database()")
    database = cur.fetchone()["current_database"]
    cur.execute("SELECT pg_database_size(current_database())")
    size_bytes = int(cur.fetchone()["pg_database_size"])

    dsn = conn.get_dsn_parameters()
    host = dsn.get("host", "?")
    port = dsn.get("port", "?")

    revision = None
    cur.execute("SELECT to_regclass('public.alembic_version')")
    if cur.fetchone()["to_regclass"] is not None:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        revision = row["version_num"] if row else None

    return {
        "server_version": server_version,
        "database": database,
        "size_bytes": size_bytes,
        "host": host,
        "port": port,
        "alembic_revision": revision,
    }


def collect_relations(cur) -> list[dict]:
    return _fetch(
        cur,
        """
        SELECT c.relname AS name,
               n.nspname AS schema,
               c.relkind AS kind,
               pg_catalog.obj_description(c.oid, 'pg_class') AS comment,
               c.reltuples::bigint AS reltuples
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p', 'v', 'm')
          AND c.relname NOT LIKE 'pg\\_%%'
          AND c.relname <> ALL(%s)
        ORDER BY c.relname
        """,
        (list(EXCLUDED_RELATIONS),),
    )


def collect_columns(cur, table: str) -> list[dict]:
    return _fetch(
        cur,
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    )


def collect_primary_keys(cur, table: str) -> set[str]:
    rows = _fetch(
        cur,
        """
        SELECT a.attname AS name
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
        JOIN pg_attribute a ON a.attrelid = rel.oid AND a.attnum = ANY(con.conkey)
        WHERE con.contype = 'p' AND ns.nspname = 'public' AND rel.relname = %s
        """,
        (table,),
    )
    return {r["name"] for r in rows}


def collect_foreign_keys(cur, table: str | None = None) -> list[dict]:
    params: tuple = ()
    where = ""
    if table is not None:
        where = "AND rel.relname = %s"
        params = (table,)
    return _fetch(
        cur,
        f"""
        SELECT con.conname AS name,
               rel.relname AS table_name,
               frel.relname AS ref_table,
               att.attname AS column_name,
               fatt.attname AS ref_column,
               con.confdeltype AS on_delete
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class frel ON frel.oid = con.confrelid
        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
        JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = ck.ord
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ck.attnum
        JOIN pg_attribute fatt ON fatt.attrelid = con.confrelid AND fatt.attnum = fk.attnum
        WHERE con.contype = 'f' AND ns.nspname = 'public' {where}
        ORDER BY rel.relname, con.conname, ck.ord
        """,
        params,
    )


def collect_checks(cur, table: str) -> list[str]:
    rows = _fetch(
        cur,
        """
        SELECT con.conname AS name, pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = rel.relnamespace
        WHERE con.contype = 'c' AND ns.nspname = 'public' AND rel.relname = %s
        ORDER BY con.conname
        """,
        (table,),
    )
    return [f"{r['name']}: {r['definition']}" for r in rows]


def collect_indexes(cur, table: str) -> list[dict]:
    rows = _fetch(
        cur,
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = %s
        ORDER BY indexname
        """,
        (table,),
    )
    return [
        {
            "name": r["indexname"],
            "definition": r["indexdef"],
            "unique": "UNIQUE" in r["indexdef"].upper(),
        }
        for r in rows
    ]


def collect_row_counts(cur, table: str, fast: bool) -> tuple[int | None, int | None]:
    cur.execute(
        "SELECT n_live_tup FROM pg_stat_user_tables WHERE relname = %s", (table,)
    )
    est_row = cur.fetchone()
    estimated = int(est_row["n_live_tup"]) if est_row else None
    if fast:
        return None, estimated
    cur.execute(f"SELECT COUNT(*) AS n FROM {_typed(table)}")
    return int(cur.fetchone()["n"]), estimated


def collect_sample(cur, table: str, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    rows = _fetch(cur, f"SELECT * FROM {_typed(table)} LIMIT %s", (limit,))
    return [{k: _jsonable(v) for k, v in row.items()} for row in rows]


def _stats_expressions(columns: list[ColumnInfo]) -> list[str]:
    exprs: list[str] = []
    for col in columns:
        q = _q(col.name)
        exprs.append(f'count(*) FILTER (WHERE {q} IS NULL) AS "{col.name}__null"')
        dtype = col.data_type.lower()
        numeric = any(
            t in dtype
            for t in ("integer", "smallint", "bigint", "numeric", "real", "double", "decimal")
        )
        temporal = "date" in dtype or "timestamp" in dtype or "time" in dtype
        boolean = "bool" in dtype

        if numeric:
            exprs.append(f'count(DISTINCT {q}) AS "{col.name}__distinct"')
            exprs.append(f'min({q}) AS "{col.name}__min"')
            exprs.append(f'max({q}) AS "{col.name}__max"')
            exprs.append(f'avg({q}) AS "{col.name}__avg"')
            exprs.append(f'sum({q}) AS "{col.name}__sum"')
        elif temporal:
            exprs.append(f'count(DISTINCT {q}) AS "{col.name}__distinct"')
            exprs.append(f'min({q}) AS "{col.name}__min"')
            exprs.append(f'max({q}) AS "{col.name}__max"')
        elif boolean:
            exprs.append(f'count(DISTINCT {q}) AS "{col.name}__distinct"')
            exprs.append(f'count(*) FILTER (WHERE {q}) AS "{col.name}__true"')
        else:
            exprs.append(f'count(DISTINCT {q}) AS "{col.name}__distinct"')
            exprs.append(f'min({q}) AS "{col.name}__min"')
            exprs.append(f'max({q}) AS "{col.name}__max"')
    return exprs


def collect_column_stats(cur, table: str, columns: list[ColumnInfo]) -> None:
    if not columns:
        return
    select_list = ", ".join(_stats_expressions(columns))
    cur.execute(f"SELECT {select_list} FROM {_typed(table)}")
    row = cur.fetchone()
    for col in columns:
        col.null_count = _as_int(row.get(f"{col.name}__null"))
        col.distinct_count = _as_int(row.get(f"{col.name}__distinct"))
        col.min_value = _as_str(row.get(f"{col.name}__min"))
        col.max_value = _as_str(row.get(f"{col.name}__max"))
        col.avg_value = _as_float(row.get(f"{col.name}__avg"))
        col.sum_value = _as_float(row.get(f"{col.name}__sum"))
        col.true_count = _as_int(row.get(f"{col.name}__true"))


def collect_top_values(cur, table: str, columns: list[ColumnInfo]) -> None:
    for col in columns:
        if col.distinct_count is None:
            continue
        if col.distinct_count <= 1 or col.distinct_count > TEXT_COLUMN_TOPN_MAX_DISTINCT:
            continue
        dtype = col.data_type.lower()
        if "int" in dtype or "numeric" in dtype or "real" in dtype or "double" in dtype:
            continue
        if "date" in dtype or "timestamp" in dtype or "bool" in dtype:
            continue
        rows = _fetch(
            cur,
            f"""
            SELECT {_q(col.name)}::text AS value, count(*) AS n
            FROM {_typed(table)}
            GROUP BY {_q(col.name)}
            ORDER BY n DESC, 1
            LIMIT %s
            """,
            (TOP_N,),
        )
        col.top_values = [(r["value"], int(r["n"])) for r in rows]


def inspect_relation(cur, rel: dict, fast: bool, schema_only: bool,
                     sample_limit: int) -> RelationInfo:
    name = rel["name"]
    kind = rel["kind"]
    is_table = kind in ("r", "p")
    is_legacy = "legacy" in name.lower()

    kind_label = {
        "r": "table",
        "p": "partitioned table",
        "v": "view",
        "m": "materialized view",
    }.get(kind) or str(kind)

    info = RelationInfo(
        name=name,
        schema=rel["schema"],
        kind=kind_label,
        comment=rel["comment"],
        is_legacy=is_legacy,
    )

    if is_table:
        cur.execute("SELECT pg_total_relation_size(%s::regclass) AS size", (name,))
        info.size_bytes = int(cur.fetchone()["size"])

    pk_cols = collect_primary_keys(cur, name) if is_table else set()
    fk_rows = collect_foreign_keys(cur, name) if is_table else []
    fk_by_column = {r["column_name"]: f"{r['ref_table']}.{r['ref_column']}" for r in fk_rows}
    info.foreign_keys = [
        ForeignKeyInfo(
            name=r["name"],
            column=r["column_name"],
            ref_table=r["ref_table"],
            ref_column=r["ref_column"],
            on_delete=_DELETE_ACTIONS.get(r["on_delete"]) or str(r["on_delete"]),
        )
        for r in fk_rows
    ]

    for c in collect_columns(cur, name):
        info.columns.append(
            ColumnInfo(
                name=c["column_name"],
                data_type=c["data_type"],
                nullable=c["is_nullable"] == "YES",
                default=c["column_default"],
                is_primary_key=c["column_name"] in pk_cols,
                fk_target=fk_by_column.get(c["column_name"]),
            )
        )

    if is_table:
        info.indexes = [
            IndexInfo(name=i["name"], definition=i["definition"], unique=i["unique"])
            for i in collect_indexes(cur, name)
        ]
        info.checks = collect_checks(cur, name)

    if schema_only:
        return info

    info.rows_exact, info.rows_estimated = collect_row_counts(cur, name, fast)

    if is_table:
        row_for_stats = info.rows_exact if info.rows_exact is not None else info.rows_estimated
        if row_for_stats is not None and row_for_stats > STATS_ROW_SOFT_LIMIT:
            info.stats_skipped = True
        else:
            collect_column_stats(cur, name, info.columns)
            collect_top_values(cur, name, info.columns)

    info.sample = collect_sample(cur, name, sample_limit)
    return info


# ---------------------------------------------------------------------------
# Conversione valori
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _as_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _human_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    size = float(n)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _truncate(value: Any, width: int = SAMPLE_VALUE_MAX) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    if len(text) > width:
        text = text[:width]
    text = " ".join(text.split())
    if len(text) > width:
        text = text[: width - 3] + "..."
    return text


def _md_cell(value: Any, width: int = 40) -> str:
    return _truncate(value, width).replace("|", "\\|")


def _configure_stdout() -> None:
    """Forza stdout/stderr in UTF-8: i dati possono contenere caratteri
    non-ASCII (apostrofi tipografici, accenti) che la codepage di default
    su Windows non riesce a serializzare, invalidando l'output JSON."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Formatter: testo
# ---------------------------------------------------------------------------


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def accent(self, text: str) -> str:
        return self._wrap("36", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)


def _rule(char: str = "-", width: int = 72) -> str:
    return char * width


def format_text(snap: Snapshot, color: bool) -> str:
    s = _Style(color)
    out: list[str] = []

    out.append(s.bold(f"=== DB SNAPSHOT - {snap.snapshot_at} ==="))
    out.append(f"Server:    {snap.server_version.split()[0]} {snap.server_version.split()[1] if len(snap.server_version.split()) > 1 else ''} @ {snap.host}:{snap.port}".rstrip())
    out.append(f"Database:  {snap.database} (size: {_human_bytes(snap.size_bytes)})")
    out.append(f"Alembic:   {snap.alembic_revision or '(assente)'}")

    for w in snap.warnings:
        out.append(s.warn(f"[!] {w}"))

    out.append("")
    out.append(_rule("="))
    out.append(s.bold(f"ENTITA'  ({len(snap.tables)} tabelle, {len(snap.views)} viste)"))
    out.append(_rule("="))

    for idx, rel in enumerate(snap.tables, start=1):
        out.extend(_format_relation_text(rel, s, idx, len(snap.tables)))

    if snap.views:
        out.append("")
        out.append(_rule("="))
        out.append(s.bold(f"VISTE  ({len(snap.views)})"))
        out.append(_rule("="))
        for rel in snap.views:
            out.extend(_format_relation_text(rel, s, None, None))

    out.append("")
    out.extend(_format_fk_graph_text(snap, s))
    out.append("")
    out.extend(_format_summary_text(snap, s))

    return "\n".join(out)


def _format_relation_text(rel: RelationInfo, s: _Style, idx: int | None, total: int | None) -> list[str]:
    out: list[str] = []
    badge = s.warn(" [ARCHIVIO]") if rel.is_legacy else ""
    prefix = f"[{idx}/{total}] " if idx is not None else ""
    header = f"{prefix}{rel.name}"
    if rel.rows_exact is not None:
        header += f"  ({rel.rows_exact} righe)"
    elif rel.rows_estimated is not None:
        header += f"  (~{rel.rows_estimated} righe)"
    out.append("")
    out.append(s.accent(header) + badge)

    if rel.comment:
        out.append(s.dim(f"  {_truncate(rel.comment, 100)}"))

    out.append(f"  Colonne ({len(rel.columns)}):")
    for c in rel.columns:
        flags: list[str] = []
        flags.append("NOT NULL" if not c.nullable else "NULL")
        if c.is_primary_key:
            flags.append("PK")
        if c.fk_target:
            flags.append(f"FK -> {c.fk_target}")
        default = ""
        if c.default and "nextval" not in c.default:
            default = f"  default {_truncate(c.default, 30)}"
        line = f"    {c.name:<28} {c.data_type:<26} {', '.join(flags)}{default}"
        out.append(line)
        extras = _column_stats_text(c)
        if extras:
            out.append(s.dim(f"      {extras}"))

    if rel.indexes:
        out.append(f"  Indici ({len(rel.indexes)}):")
        for i in rel.indexes:
            uniq = " UNIQUE" if i.unique else ""
            out.append(f"    {i.name}{uniq}")

    if rel.checks:
        out.append(f"  CHECK ({len(rel.checks)}):")
        for chk in rel.checks:
            out.append(f"    {_truncate(chk, 90)}")

    if rel.foreign_keys:
        out.append("  FK outgoing:")
        for fk in rel.foreign_keys:
            out.append(
                f"    {fk.column} -> {fk.ref_table}.{fk.ref_column} (ON DELETE {fk.on_delete})"
            )

    if rel.stats_skipped:
        out.append(s.warn("  Statistiche colonne saltate (tabella grande)."))

    if rel.sample:
        out.append(f"  Sample ({len(rel.sample)} righe):")
        for row in rel.sample:
            pairs = ", ".join(f"{k}={_truncate(v, 40)}" for k, v in row.items())
            out.append(f"    {_truncate(pairs, 140)}")
    elif rel.rows_exact == 0:
        out.append(s.dim("  Sample: (vuoto)"))

    return out


def _column_stats_text(c: ColumnInfo) -> str:
    parts: list[str] = []
    if c.null_count:
        parts.append(f"null={c.null_count}")
    if c.distinct_count is not None:
        parts.append(f"distinct={c.distinct_count}")
    if c.min_value is not None or c.max_value is not None:
        parts.append(f"range=[{_truncate(c.min_value, 24)} .. {_truncate(c.max_value, 24)}]")
    if c.avg_value is not None:
        parts.append(f"avg={c.avg_value:.2f}")
    if c.sum_value is not None and c.name == "metric_value":
        parts.append(f"sum={c.sum_value:.2f}")
    if c.true_count is not None:
        parts.append(f"true={c.true_count}")
    if c.top_values:
        top = ", ".join(f"{_truncate(v, 18)}({n})" for v, n in c.top_values[:5])
        parts.append(f"top: {top}")
    return " | ".join(parts)


def _format_fk_graph_text(snap: Snapshot, s: _Style) -> list[str]:
    out = [_rule("="), s.bold("GRAFO FK"), _rule("=")]
    count = 0
    for rel in snap.tables:
        for fk in rel.foreign_keys:
            count += 1
            out.append(
                f"  {rel.name}.{fk.column} -> {fk.ref_table}.{fk.ref_column} (ON DELETE {fk.on_delete})"
            )
    if count == 0:
        out.append(s.dim("  (nessuna chiave esterna)"))
    return out


def _format_summary_text(snap: Snapshot, s: _Style) -> list[str]:
    total_rows = sum(r.rows_exact or 0 for r in snap.tables)
    out = [_rule("="), s.bold("RIEPILOGO"), _rule("=")]
    out.append(f"  Tabelle:    {len(snap.tables)}")
    out.append(f"  Viste:      {len(snap.views)}")
    out.append(f"  Righe tot:  {total_rows}")
    out.append(f"  Dimensione: {_human_bytes(snap.size_bytes)}")
    return out


# ---------------------------------------------------------------------------
# Formatter: Markdown
# ---------------------------------------------------------------------------


def format_markdown(snap: Snapshot) -> str:
    out: list[str] = []
    out.append(f"# DB Snapshot - {snap.snapshot_at}")
    out.append("")
    out.append(f"- **Server**: {snap.server_version}")
    out.append(f"- **Host**: {snap.host}:{snap.port}")
    out.append(f"- **Database**: `{snap.database}` ({_human_bytes(snap.size_bytes)})")
    out.append(f"- **Alembic**: `{snap.alembic_revision or 'assente'}`")
    out.append("")

    for w in snap.warnings:
        out.append(f"> [!WARNING]")
        out.append(f"> {w}")
        out.append("")

    for rel in snap.tables:
        out.extend(_format_relation_md(rel))
    for rel in snap.views:
        out.extend(_format_relation_md(rel))

    out.append("## Grafo FK")
    out.append("")
    count = 0
    for rel in snap.tables:
        for fk in rel.foreign_keys:
            count += 1
            out.append(f"- `{rel.name}.{fk.column}` -> `{fk.ref_table}.{fk.ref_column}` (ON DELETE {fk.on_delete})")
    if count == 0:
        out.append("_Nessuna chiave esterna._")
    out.append("")

    total_rows = sum(r.rows_exact or 0 for r in snap.tables)
    out.append("## Riepilogo")
    out.append("")
    out.append(f"- Tabelle: **{len(snap.tables)}**")
    out.append(f"- Viste: **{len(snap.views)}**")
    out.append(f"- Righe totali: **{total_rows}**")
    out.append(f"- Dimensione: **{_human_bytes(snap.size_bytes)}**")
    out.append("")
    return "\n".join(out)


def _format_relation_md(rel: RelationInfo) -> list[str]:
    out: list[str] = []
    rows = rel.rows_exact if rel.rows_exact is not None else f"~{rel.rows_estimated}"
    legacy = " _(archivio)_" if rel.is_legacy else ""
    out.append(f"## `{rel.name}` ({rel.kind}){legacy}")
    out.append("")
    if rel.comment:
        out.append(f"> {rel.comment}")
        out.append("")
    out.append(f"**Righe**: {rows}  |  **Dimensione**: {_human_bytes(rel.size_bytes)}")
    out.append("")
    out.append("| Colonna | Tipo | Null | Vincoli |")
    out.append("|---|---|---|---|")
    for c in rel.columns:
        cons: list[str] = []
        if c.is_primary_key:
            cons.append("PK")
        if c.fk_target:
            cons.append(f"FK -> {c.fk_target}")
        if not c.nullable:
            cons.append("NOT NULL")
        cons_str = ", ".join(cons) if cons else "-"
        out.append(f"| `{c.name}` | {c.data_type} | {'sì' if c.nullable else 'no'} | {cons_str} |")
    out.append("")

    if rel.indexes:
        out.append("**Indici**:")
        out.append("")
        for i in rel.indexes:
            out.append(f"- `{i.name}`{' (unique)' if i.unique else ''}")
        out.append("")

    if rel.checks:
        out.append("**CHECK**:")
        out.append("")
        for chk in rel.checks:
            out.append(f"- `{chk}`")
        out.append("")

    if rel.sample:
        out.append("**Sample**:")
        out.append("")
        keys = list(rel.sample[0].keys())
        out.append("| " + " | ".join(keys) + " |")
        out.append("|" + "|".join(["---"] * len(keys)) + "|")
        for row in rel.sample:
            out.append("| " + " | ".join(_md_cell(row.get(k)) for k in keys) + " |")
        out.append("")

    return out


# ---------------------------------------------------------------------------
# Formatter: JSON
# ---------------------------------------------------------------------------


def format_json(snap: Snapshot) -> str:
    payload = {
        "snapshot_at": snap.snapshot_at,
        "server": {
            "version": snap.server_version,
            "host": snap.host,
            "port": snap.port,
        },
        "database": {"name": snap.database, "size_bytes": snap.size_bytes},
        "alembic_revision": snap.alembic_revision,
        "summary": {
            "tables": len(snap.tables),
            "views": len(snap.views),
            "total_rows": sum(r.rows_exact or 0 for r in snap.tables),
            "size_bytes": snap.size_bytes,
        },
        "tables_empty": bool(snap.tables)
        and all((r.rows_exact or 0) == 0 for r in snap.tables),
        "tables": [asdict(r) for r in snap.tables],
        "views": [asdict(r) for r in snap.views],
        "warnings": snap.warnings,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=_jsonable)


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------


def build_snapshot(conn, cur, *, fast: bool, schema_only: bool, sample_limit: int,
                   include_views: bool) -> Snapshot:
    db = collect_database_info(conn, cur)
    relations = collect_relations(cur)

    tables: list[RelationInfo] = []
    views: list[RelationInfo] = []
    for rel in relations:
        is_view = rel["kind"] in ("v", "m")
        if is_view and not include_views:
            continue
        info = inspect_relation(cur, rel, fast, schema_only, sample_limit)
        (views if is_view else tables).append(info)

    snap = Snapshot(
        snapshot_at=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        server_version=db["server_version"],
        host=db["host"],
        port=db["port"],
        database=db["database"],
        size_bytes=db["size_bytes"],
        alembic_revision=db["alembic_revision"],
        tables=tables,
        views=views,
    )

    if not schema_only:
        if fast:
            snap.warnings.append(
                "Conteggi stimati dal catalogo (--fast): possono risultare 0 finche' "
                "non viene eseguito ANALYZE. Usa il default per i conteggi esatti."
            )
        elif tables:
            empty = [t.name for t in tables if (t.rows_exact or 0) == 0]
            if len(empty) == len(tables):
                snap.warnings.append(
                    f"TUTTE LE TABELLE SONO VUOTE (0 righe in {len(tables)}/{len(tables)}). "
                    "Popola con: make ingest  e  make ingest-ga4"
                )
            elif empty:
                snap.warnings.append(
                    f"{len(empty)}/{len(tables)} tabelle vuote: {', '.join(empty)}"
                )
    return snap


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        description="Fotografia read-only del database Postgres del progetto."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="output JSON")
    group.add_argument("--md", action="store_true", help="output Markdown")
    parser.add_argument("--url", default=None, help="DSN di override (default: DATABASE_URL/.env)")
    parser.add_argument("--fast", action="store_true", help="conteggi stimati dal catalogo (no COUNT(*))")
    parser.add_argument("--schema-only", action="store_true", help="solo struttura, nessun dato")
    parser.add_argument("--sample", type=int, default=3, help="righe di esempio per tabella (default 3)")
    parser.add_argument("--exclude-views", action="store_true", help="salta le viste")
    parser.add_argument("--no-color", action="store_true", help="disabilita colori ANSI")
    args = parser.parse_args(argv)

    try:
        url = build_database_url(args.url)
    except Exception as exc:  # pragma: no cover - difensivo
        print(f"Errore nella costruzione della DSN: {exc}", file=sys.stderr)
        return 2

    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.Error as exc:
        print(f"Errore di connessione al database: {exc}", file=sys.stderr)
        print(
            "Verifica che 'docker compose ps' mostri td_postgres healthy e che .env sia valorizzato.",
            file=sys.stderr,
        )
        return 1

    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            snap = build_snapshot(
                conn,
                cur,
                fast=args.fast,
                schema_only=args.schema_only,
                sample_limit=args.sample,
                include_views=not args.exclude_views,
            )
    finally:
        conn.close()

    if args.json:
        print(format_json(snap))
    elif args.md:
        print(format_markdown(snap))
    else:
        color = (not args.no_color) and sys.stdout.isatty()
        print(format_text(snap, color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
