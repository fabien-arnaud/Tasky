#!/bin/bash
# Rapatrie les données de prod depuis le VPS pour debug local.

SSH_USER="fabien"
SSH_HOST="51.15.190.170"
REMOTE_DATA_DIR="/home/fabien/tasky/data"
SSH_KEY="$HOME/.ssh/id_ed25519"

LOCAL_DATA_DIR="$(dirname "$0")/data"

echo "Rapatriement des données depuis $SSH_HOST..."
scp -i "$SSH_KEY" \
    "$SSH_USER@$SSH_HOST:$REMOTE_DATA_DIR/tasks.csv" \
    "$SSH_USER@$SSH_HOST:$REMOTE_DATA_DIR/node_positions.json" \
    "$LOCAL_DATA_DIR/"

echo "Done. Fichiers dans $LOCAL_DATA_DIR/"
