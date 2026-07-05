#!/bin/bash
# Réinitialise le mot de passe d'un utilisateur Tasky : usage: ./reset_password.sh
set -euo pipefail

USERS_JSON="/home/fabien/tasky/auth/users.json"

mapfile -t NAMES < <(python3 -c "
import json
users = json.load(open('$USERS_JSON'))
for name in sorted(users):
    print(name)
")

if [[ ${#NAMES[@]} -eq 0 ]]; then
  echo "Aucun utilisateur trouvé dans $USERS_JSON" >&2
  exit 1
fi

echo "Utilisateurs :"
for i in "${!NAMES[@]}"; do
  echo "  $((i+1))) ${NAMES[$i]}"
done

read -rp "Réinitialiser le mot de passe de qui ? (numéro) : " CHOICE

if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || (( CHOICE < 1 || CHOICE > ${#NAMES[@]} )); then
  echo "Choix invalide." >&2
  exit 1
fi

NAME="${NAMES[$((CHOICE-1))]}"

read -rp "Confirmer la réinitialisation du mot de passe de '$NAME' ? (o/N) : " CONFIRM
if [[ "$CONFIRM" != "o" && "$CONFIRM" != "O" ]]; then
  echo "Annulé."
  exit 0
fi

python3 -c "
import json
path = '$USERS_JSON'
users = json.load(open(path))
users['$NAME']['password_hash'] = None
with open(path, 'w') as f:
    json.dump(users, f, indent=2, ensure_ascii=False)
    f.write('\n')
"

echo "Mot de passe de '$NAME' réinitialisé. Il/elle devra en choisir un nouveau à la prochaine connexion."
