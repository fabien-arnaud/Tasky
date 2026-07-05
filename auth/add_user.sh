#!/bin/bash
# Ajoute un nouvel ami à Tasky : usage: ./add_user.sh <prenom>
set -euo pipefail

RAW_NAME="${1:-}"
if [[ -z "$RAW_NAME" ]]; then
  echo "Usage: $0 <prenom>" >&2
  exit 1
fi
NAME=$(echo "$RAW_NAME" | tr '[:upper:]' '[:lower:]')
if [[ ! "$NAME" =~ ^[a-z][a-z0-9]{1,20}$ ]]; then
  echo "Nom invalide (lettres/chiffres uniquement, doit commencer par une lettre)." >&2
  exit 1
fi

AUTH_DIR="/home/fabien/tasky/auth"
DATA_DIR="/home/fabien/tasky/data/${NAME}"
SEED_DIR="/home/fabien/tasky/app/seed"

python3 - "$NAME" "$AUTH_DIR/users.json" << 'PYEOF'
import json, sys
name, users_path = sys.argv[1], sys.argv[2]
with open(users_path) as f:
    users = json.load(f)
if name in users:
    print(f"'{name}' existe déjà dans users.json", file=sys.stderr)
    sys.exit(1)
users[name] = {"password_hash": None}
with open(users_path, "w") as f:
    json.dump(users, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF

mkdir -p "$DATA_DIR/history"
cp "$SEED_DIR/tasks.example.csv" "$DATA_DIR/"
cp "$SEED_DIR/node_positions.example.json" "$DATA_DIR/"

sudo /home/fabien/tasky/auth/root_helper.sh "$NAME"

echo "Ami '$NAME' ajouté. Il peut aller sur https://tasky.dynetah.com/ et entrer son prénom pour créer son mot de passe."
