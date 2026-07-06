# Tasky — Notes pour Claude Code

## Ce qu'est ce projet

Application web de gestion de tâches avec dépendances, visualisée comme un graphe.
Stack : Python / Plotly Dash + Dash Cytoscape (Cytoscape.js). Un seul fichier `tasky.py` (~2100 lignes).
Déployée sur une VPS propriétaire, accessible via `tasky.dynetah.com`, pour plusieurs
utilisateurs (fabien, yoan, davy...) avec un login self-service.

**Déploiement multi-utilisateur (nginx, auth, systemd, sudoers, backup) : voir
[../README.md](../README.md).** Ce fichier-ci ne couvre que le code de l'appli.

## Architecture

### Fichier unique
Tout le code est dans `tasky.py` : modèle de données, logique métier, layout Dash, callbacks.

### Stockage local versionné
Les données vivent dans `DATA_DIR` (une valeur par utilisateur en prod, ex.
`/home/fabien/tasky/data/<prenom>`, non commité dans git) :
- `tasks.csv` — les tâches
- `node_positions.json` — positions X/Y des nœuds sur le canvas
- `history/` — snapshots versionnés (max 100), un dossier numéroté par version

La classe `LocalVersionedStorage` gère lecture/écriture + historique undo.
Variable d'env : `DATA_DIR` (défaut en dev local : `./data`).
Fichiers exemples utilisés pour seeder un `DATA_DIR` vide : `seed/tasks.example.csv`
et `seed/node_positions.example.json`.

**Undo** : bouton "↩" dans l'UI. Retour en arrière sur les deux fichiers ensemble.
Après un undo, le prochain changement détruit les versions "futures".

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

## Règles de travail

- Toujours proposer et expliquer avant de modifier le code. L'utilisateur valide avant.
- Ne pas modifier les dossiers `data/<prenom>/` (données de prod, non commitées).
- `venv/`, `.env` sont dans `.gitignore` (au niveau de `/home/fabien/tasky/`).
- Convention de version : `v2.0.XXX` dans la constante `VERSION` en tête de `tasky.py`.
