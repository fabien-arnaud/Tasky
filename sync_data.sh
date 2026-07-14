#!/bin/bash
# Synchronise les données entre le VPS et le dossier local data/
# Usage : ./sync_data.sh [pull|push] [user]
#         Sans arguments : mode interactif

VPS_HOST="fabien@tasky.dynetah.com"
VPS_BASE="/home/fabien/tasky/data"
LOCAL_BASE="$(cd "$(dirname "$0")" && pwd)/data"
FILES=("tasks.csv" "node_positions.json")
KNOWN_USERS=($(ssh "$VPS_HOST" "ls $VPS_BASE/" 2>/dev/null))
if [ ${#KNOWN_USERS[@]} -eq 0 ]; then
    KNOWN_USERS=("fabien")
fi

do_pull() {
    local user="$1"
    echo "⬇  VPS ($user) → local"
    for f in "${FILES[@]}"; do
        scp "$VPS_HOST:$VPS_BASE/$user/$f" "$LOCAL_BASE/$f" && echo "  OK $f"
    done
}

do_push() {
    local user="$1"
    echo ""
    echo "⬆  local → VPS ($user)"
    echo "ATTENTION : cela écrase les données de $user en production."
    read -p "Tape \"$user\" pour confirmer : " confirm
    if [ "$confirm" = "$user" ]; then
        for f in "${FILES[@]}"; do
            scp "$LOCAL_BASE/$f" "$VPS_HOST:$VPS_BASE/$user/$f" && echo "  OK $f"
        done
    else
        echo "Annulé."
    fi
}

CHOSEN_USER="${KNOWN_USERS[0]}"
choose_user() {
    echo ""
    echo "Utilisateur :"
    for i in "${!KNOWN_USERS[@]}"; do
        echo "  $((i+1)). ${KNOWN_USERS[$i]}"
    done
    local next=$((${#KNOWN_USERS[@]}+1))
    echo "  $next. autre"
    read -p "Choix : " uchoice
    if [[ "$uchoice" -ge 1 && "$uchoice" -le "${#KNOWN_USERS[@]}" ]] 2>/dev/null; then
        CHOSEN_USER="${KNOWN_USERS[$((uchoice-1))]}"
    elif [[ "$uchoice" -eq "$next" ]] 2>/dev/null; then
        read -p "Nom d'utilisateur : " CHOSEN_USER
    else
        CHOSEN_USER="${KNOWN_USERS[0]}"
    fi
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

choose_user

case "$dchoice" in
    1) do_pull "$CHOSEN_USER" ;;
    2) do_push "$CHOSEN_USER" ;;
    *) echo "Choix invalide."; exit 1 ;;
esac
