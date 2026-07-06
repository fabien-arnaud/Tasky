# Tasky — Notes pour Claude Code

## Ce qu'est ce projet

Application web de gestion de tâches avec dépendances, visualisée comme un graphe.
Stack : Python / Plotly Dash + Dash Cytoscape (Cytoscape.js). Un seul fichier `tasky.py` (~2300 lignes).
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
Fichiers exemples pour seeder un `DATA_DIR` vide : `seed/tasks.example.csv`
et `seed/node_positions.example.json`.

**Undo** : bouton "↩" dans l'UI. Retour en arrière sur les deux fichiers ensemble.
Après un undo, le prochain changement détruit les versions "futures".

### Modèle de données (`tasks.csv`)
Colonnes : `id, type, status, location, description, predecessors, quick`
- `type` : `F` (faire) ou `A` (acheter)
- `status` brut (stocké dans le CSV) : `TODO, DONE, PRIO, WIP`
- `predecessors` : IDs séparés par `-`
- `quick` : `1` si tâche rapide

### Logique métier clé — statuts dérivés
`compute_statuses()` calcule des statuts dérivés à partir du statut brut :

| Statut dérivé | Condition |
|---|---|
| `TOPRIO` | Ancêtre d'une tâche `PRIO`, avec au moins un prédécesseur non-DONE |
| `TOPRIO_READY` | Ancêtre d'une tâche `PRIO`, sans prédécesseur non-DONE (actionnable) |
| `Ready` | Aucun prédécesseur non-DONE, pas sur le chemin critique |
| `Ready-Critic` | `Ready` + seul verrou d'un successeur direct |

Les statuts `WIP` et `DONE` sont toujours préservés tels quels (non écrasés).
`count_lockers` : nombre de prédécesseurs non-DONE pour chaque tâche.
`_would_create_cycle()` : protection anti-cycle avant ajout de dépendance.

### Système visuel — VISUAL_TABLE
Les attributs visuels des nœuds (forme, fond, bordure) sont définis dans une table Python
`(type, status, quick) → {shape, bg, bw, bc}`, injectés dans les données du nœud et lus
par le stylesheet Cytoscape via `data(...)`. Pas de cascade CSS.

Trois thèmes définis : `HISTORIC`, `NEWGEN` (actif), `DARK`.
Constante `CURRENT_THEME` en tête de fichier pour switcher.

### État client (dcc.Store)
- `meta-store` : tous les dicts métier (types, statuts, prédécesseurs...)
- `view-mode` : `"planning"` ou `"execution"`
- Autres stores : cache positions, viewport, triggers

### Vues
- **Planification** : graphe complet avec groupes par location (compound nodes Cytoscape)
- **Exécution** : vue filtrée — `compute_exec_positions()` calcule quels nœuds afficher
  et leurs positions X/Y. Le JS cache tout nœud sans position.
  - `row0` : actionnables (Ready, WIP, TOPRIO_READY + PRIO sans verrou)
  - `row1` : tout successeur non-DONE d'un nœud row0 (même location)
  - Tri dans chaque projet : WIP type F en tête, puis TOPRIO_READY/PRIO, puis quick, puis reste (WIP type A inclus)

## Règles de travail

- Toujours proposer et expliquer avant de modifier le code. L'utilisateur valide avant.
- Ne pas modifier les dossiers `data/<prenom>/` (données de prod, non commitées).
- `venv/`, `.env` sont dans `.gitignore`.
- Convention de version : `v2.1.XXX` dans la constante `VERSION` en tête de `tasky.py`.
- Déployer avec `app/deploy.sh` (depuis le repo local) ou `app/update.sh` (directement sur le VPS).
