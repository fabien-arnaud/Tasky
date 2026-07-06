# Tasky

Application web de gestion de tâches avec dépendances, visualisée comme un graphe interactif.

Stack : Python / Plotly Dash + Dash Cytoscape.

En production, ce code tourne pour plusieurs utilisateurs sur un VPS — voir
[../README.md](../README.md) pour l'architecture de déploiement multi-utilisateur.
Ce qui suit concerne uniquement le lancement en local pour développer.

## Prérequis

- Python 3.9 ou plus récent
- Git

## Installation

```bash
# 1. Cloner le repo
git clone https://github.com/fabien-arnaud/Tasky.git
cd Tasky/app

# 2. Créer un environnement virtuel
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Initialiser les données
mkdir -p data
cp seed/tasks.example.csv data/tasks.csv
cp seed/node_positions.example.json data/node_positions.json
```

## Lancer l'application

```bash
python tasky.py
```

Puis ouvrir [http://localhost:8050](http://localhost:8050) dans un navigateur.

## Mettre à jour

```bash
git pull
# Redémarrer tasky.py
```

## Variables d'environnement (optionnel)

| Variable | Défaut | Description |
|----------|--------|-------------|
| `DATA_DIR` | `./data` | Répertoire des fichiers de données |
