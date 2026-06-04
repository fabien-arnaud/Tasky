# Tasky — Notes pour Claude Code

## Ce qu'est ce projet

Application web de gestion de tâches avec dépendances, visualisée comme un graphe.
Stack : Python / Plotly Dash + Dash Cytoscape (Cytoscape.js). Un seul fichier `tasky.py` (~2100 lignes).
Déployée sur une VPS propriétaire, accessible via `tasky.dynetah.com`.

## Architecture

### Fichier unique
Tout le code est dans `tasky.py` : modèle de données, logique métier, layout Dash, callbacks.

### Stockage local versionné
Les données vivent dans `data/` (non commité dans git) :
- `data/tasks.csv` — les tâches
- `data/node_positions.json` — positions X/Y des nœuds sur le canvas
- `data/history/` — snapshots versionnés (max 100), un dossier numéroté par version

La classe `LocalVersionedStorage` gère lecture/écriture + historique undo.
Variable d'env optionnelle : `DATA_DIR` (défaut : `./data`).

**Undo** : bouton "↩" dans l'UI. Retour en arrière sur les deux fichiers ensemble.
Après un undo, le prochain changement détruit les versions "futures".

### Backup GitHub (à implémenter)
Un script de backup horaire vers le repo privé `fabien-arnaud/tasky-data` est prévu.
Variable d'env : `GITHUB_BACKUP_TOKEN`.
Déclenchement uniquement si les fichiers ont changé depuis le dernier backup (hash).

### Modèle de données (`tasks.csv`)
Colonnes : `id, type, status, location, description, predecessors, quick`
- `type` : `F` (faire) ou `A` (acheter)
- `status` brut : `TODO, DONE, PRIO, ToBuy, Ready, ...`
- `predecessors` : IDs séparés par `-`
- `quick` : `1` si tâche rapide

### Logique métier clé
- `compute_statuses()` : calcule les statuts dérivés — `TOPRIO` (chemin critique vers les tâches `PRIO`), `Ready/ToBuy-Critic` (seul verrou d'un successeur)
- `count_lockers` : nombre de prédécesseurs non-DONE pour chaque tâche
- `_would_create_cycle()` : protection anti-cycle avant ajout de dépendance

### État client (dcc.Store)
- `meta-store` : tous les dicts métier (types, statuts, prédécesseurs...)
- `view-mode` : `"planning"` ou `"execution"`
- Autres stores : cache positions, viewport, triggers

### Vues
- **Planification** : graphe complet avec groupes par location
- **Exécution** : vue filtrée, tâches actionnables seulement, layout calculé côté serveur

## Déploiement (à faire)

- Serveur : systemd + gunicorn
- Reverse proxy : nginx sur `tasky.dynetah.com`, Basic Auth, SSL Let's Encrypt
- Variables d'env dans un fichier `.env` (non commité) : `DATA_DIR`, `GITHUB_BACKUP_TOKEN`
- Cron horaire pour backup vers `fabien-arnaud/tasky-data` (uniquement si modif)

## Règles de travail

- Toujours proposer et expliquer avant de modifier le code. L'utilisateur valide avant.
- Ne pas modifier `data/` (données de prod, non commitées).
- `data/`, `venv/`, `.env` sont dans `.gitignore`.
- Convention de version : `v2.0.XXX` dans la constante `VERSION` en tête de `tasky.py`.
