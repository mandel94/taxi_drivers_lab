#!/usr/bin/env bash
# Backup del database Postgres del progetto (container td_postgres) con pg_dump.
#
#   bash scripts/backup_db.sh
#
# - Scrive td_AAAAMMGG_HHMMSS.sql.gz in BACKUP_DIR (default: <profilo utente>/Backups/taxidrivers,
#   FUORI da OneDrive: un dump da centinaia di MB non va sincronizzato e un conflitto di
#   sincronizzazione non deve poter toccare l'unica copia).
# - Le credenziali sono quelle del container (POSTGRES_USER/POSTGRES_DB dentro td_postgres):
#   nessuna password passa dalla riga di comando o dai log.
# - Il dump e' scritto su un file temporaneo e rinominato solo se supera i controlli
#   (gzip integro, dimensione minima, riga finale di pg_dump): un backup a meta' non sostituisce mai
#   uno buono e non viene mai contato come backup.
# - Il dump della domenica si conserva 90 giorni (suffisso _weekly), gli altri 14.
# - BACKUP_COPY_DIR (facoltativa, es. un disco esterno o una cartella di rete): se impostata e
#   raggiungibile, riceve una copia del file. Un backup sullo stesso disco non protegge da un guasto
#   del disco.
# Codice di uscita: 0 = backup valido; diverso da zero = nessun backup nuovo.
set -u
set -o pipefail

CONTAINER="${BACKUP_CONTAINER:-td_postgres}"
BACKUP_DIR="${BACKUP_DIR:-${USERPROFILE:+$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")}/Backups/taxidrivers}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/taxidrivers}"
MIN_BYTES="${BACKUP_MIN_BYTES:-1048576}"   # sotto 1 MB il dump e' certamente incompleto
KEEP_DAILY_DAYS="${BACKUP_KEEP_DAILY_DAYS:-14}"
KEEP_WEEKLY_DAYS="${BACKUP_KEEP_WEEKLY_DAYS:-90}"

# Come in run_refresh.sh: senza terminale il wrapper docker di MSYS2 non funziona.
here="$(cd "$(dirname "$0")" && pwd)"
export PATH="$here/bin:$PATH"
if [ -n "${USERPROFILE:-}" ]; then
  export DOCKER_CONFIG="$(cygpath -w "$USERPROFILE")\\.docker"
fi

fail() { echo "BACKUP FALLITO: $*" >&2; rm -f "${tmp:-}"; exit 1; }

mkdir -p "$BACKUP_DIR" || fail "non riesco a creare $BACKUP_DIR"
docker info >/dev/null 2>&1 || fail "Docker non risponde"
docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
  || fail "il container $CONTAINER non e' in esecuzione"

stamp="$(date +%Y%m%d_%H%M%S)"
suffix=""
[ "$(date +%u)" = "7" ] && suffix="_weekly"
final="$BACKUP_DIR/td_${stamp}${suffix}.sql.gz"
tmp="$final.part"

echo "==> Backup di $CONTAINER in $final"
docker exec "$CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' \
  | gzip -6 > "$tmp" || fail "pg_dump o gzip hanno restituito un errore"

gzip -t "$tmp" 2>/dev/null || fail "il file compresso non e' integro"
size="$(wc -c < "$tmp" | tr -d ' ')"
[ "$size" -ge "$MIN_BYTES" ] || fail "dimensione sospetta: $size byte (minimo $MIN_BYTES)"
gzip -dc "$tmp" | tail -n 5 | grep -q "PostgreSQL database dump complete" \
  || fail "manca la riga finale di pg_dump: il dump e' incompleto"

mv "$tmp" "$final"
echo "==> OK: $(( size / 1024 / 1024 )) MB"

if [ -n "${BACKUP_COPY_DIR:-}" ]; then
  if mkdir -p "$BACKUP_COPY_DIR" 2>/dev/null && cp "$final" "$BACKUP_COPY_DIR/"; then
    echo "==> Copia in $BACKUP_COPY_DIR"
  else
    echo "ATTENZIONE: copia in $BACKUP_COPY_DIR non riuscita (il backup locale e' valido)." >&2
  fi
fi

# Retention: giornalieri 14 giorni, domenicali 90. Solo file di questo script.
find "$BACKUP_DIR" -maxdepth 1 -name 'td_*.sql.gz' ! -name '*_weekly.sql.gz' -mtime +"$KEEP_DAILY_DAYS" -delete 2>/dev/null
find "$BACKUP_DIR" -maxdepth 1 -name 'td_*_weekly.sql.gz' -mtime +"$KEEP_WEEKLY_DAYS" -delete 2>/dev/null
exit 0
