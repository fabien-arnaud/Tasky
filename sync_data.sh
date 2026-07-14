#!/bin/bash
# Synchronise les données entre le VPS et le dossier local data/
# Usage : ./sync_data.sh [pull|push] [user]
#         Sans arguments : mode interactif

VPS_HOST="fabien@tasky.dynetah.com"
VPS_BASE="/home/fabien/tasky/data"
LOCAL_BASE="$(cd "$(dirname "$0")" && pwd)/data"
FILES=("tasks.csv" "node_positions.json")
KNOWN_USERS=("fabien" "yoan" "davy")

do_pull() {
    local user="$1"
    echo "⬇  VPS ($user) → local"
    for f in "${FILES[@]}"; do
        scp "$VPS_HOST:$VPS_BASE/$user/$f" "$LOCAL_BASE/$f" && echo "  OK $f"
    done
}

do_push() {
    local user="$1"
    echo "⬆  local → VPS ($user)"
    echo "Attention : cela remplace les données de $user en production."
    read -p "Confirmer ? (oui/non) : " confirm
    if [ "$confirm" = "oui" ]; then
        for f in "${FILES[@]}"; do
            scp "$LOCAL_BASE/$f" "$VPS_HOST:$VPS_BASE/$user/$f" && echo "  OK $f"
        done
    else
        echo "Annulé."
    fi
}

choose_user() {
    echo ""
    echo "Utilisateur :"
    for i in "${!KNOWN_USERS[@]}"; do
        echo "  $((i+1)). ${KNOWN_USERS[$i]}"
    done
    echo "  4. autre"
    read -p "Choix : " uchoice
    case "$uchoice" in
        1) echo "fabien" ;;
        2) echo "yoan" ;;
        3) echo "davy" ;;
        4) read -p "Nom d'utilisateur : " custom; echo "$custom" ;;
        *) echo "fabien" ;;
    esac
}

# --- Mode avec arguments ---
if [ -n "$1" ]; then
    user="${2:-fabien}"
    case "$1" in
        pull) do_pull "$user" ;;
        push) do_push "$user" ;;
        *)
            echo "Usage : $0 [pull|push] [user]"
            echo "        Sans arguments : mode interactif"
            exit 1 ;;
    esac
    exit 0
fi

# --- Mode interactif ---
echo "=== Sync données Tasky ==="
echo ""
echo "Direction :"
echo "  1. pull  — récupérer les données du VPS en local (pour tester)"
echo "  2. push  — envoyer les données locales vers le VPS (modif prod)"
read -p "Choix : " dchoice

user=$(choose_user)

case "$dchoice" in
    1) do_pull "$user" ;;
    2) do_push "$user" ;;
    *) echo "Choix invalide."; exit 1 ;;
esac
