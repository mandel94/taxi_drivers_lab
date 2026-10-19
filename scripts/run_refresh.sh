#!/usr/bin/env bash
# Aggiornamento giornaliero dei dati: articoli, GA4 (per articolo, sito e canali) e dbt.
# Lancia 'make refresh' dalla root del progetto e salva l'output in logs/refresh_AAAA-MM-GG.log.
# Pensato per essere chiamato da scripts/run_refresh.cmd (Utilita' di pianificazione di
# Windows) dentro MSYS2/UCRT64, ma funziona anche a mano:  bash scripts/run_refresh.sh
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

# Senza terminale il wrapper docker di MSYS2 (winpty) non funziona: lo shim in scripts/bin
# lo sostituisce solo per questo script. In MSYS2 HOME non e' il profilo Windows, quindi
# docker non troverebbe il plugin 'compose': si indica a mano la sua cartella di configurazione.
export PATH="$PWD/scripts/bin:$PATH"
if [ -n "${USERPROFILE:-}" ]; then
  export DOCKER_CONFIG="$(cygpath -w "$USERPROFILE")\\.docker"
fi

# Docker Desktop deve essere in esecuzione. Se non risponde (PC appena acceso, app chiusa)
# lo si avvia e si attende fino a 4 minuti.
ensure_docker() {
  docker info >/dev/null 2>&1 && return 0
  echo "Docker non risponde: avvio Docker Desktop e attendo (max 4 minuti)..."
  DD="/c/Program Files/Docker/Docker/Docker Desktop.exe"
  [ -x "$DD" ] && ("$DD" >/dev/null 2>&1 &)
  for _ in $(seq 1 48); do
    sleep 5
    docker info >/dev/null 2>&1 && { echo "Docker pronto."; return 0; }
  done
  return 1
}

LOG="logs/refresh_$(date +%F).log"
{
  echo "===== $(date '+%F %T') inizio refresh ====="
  if ensure_docker; then
    make refresh
    rc=$?
  else
    echo "ERRORE: Docker non disponibile dopo 4 minuti, refresh non eseguito."
    rc=3
  fi
  echo "===== $(date '+%F %T') fine refresh (exit $rc) ====="
} >> "$LOG" 2>&1

# Conserva 30 giorni di log.
find logs -name 'refresh_*.log' -mtime +30 -delete 2>/dev/null
exit "$rc"
