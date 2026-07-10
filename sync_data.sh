#!/bin/bash
# Synchronise les données entre le VPS et le dossier local data/
# Usage : ./sync_data.sh pull [user]   — VPS → local
#         ./sync_data.sh push [user]   — local → VPS

VPS_HOST="fabien@tasky.dynetah.com"
VPS_BASE="/home/fabien/tasky/data"
LOCAL_BASE="$(cd "$(dirname "$0")" && pwd)/data"
USER="${2:-fabien}"

VPS_DIR="$VPS_BASE/$USER"
FILES=("tasks.csv" "node_positions.json")

case "$1" in
  pull)
    echo "⬇  VPS ($USER) → local"
    for f in "${FILES[@]}"; do
      scp "$VPS_HOST:$VPS_DIR/$f" "$LOCAL_BASE/$f" && echo "  OK $f"
    done
    ;;
  push)
    echo "⬆  local → VPS ($USER)"
    echo "Attention : cela remplace les données en production."
    read -p "Confirmer ? (oui/non) : " confirm
    if [ "$confirm" = "oui" ]; then
      for f in "${FILES[@]}"; do
        scp "$LOCAL_BASE/$f" "$VPS_HOST:$VPS_DIR/$f" && echo "  OK $f"
      done
    else
      echo "Annulé."
    fi
    ;;
  *)
    echo "Usage : $0 pull [user]  — VPS vers local"
    echo "        $0 push [user]  — local vers VPS (avec confirmation)"
    echo "user par défaut : fabien"
    exit 1
    ;;
esac
