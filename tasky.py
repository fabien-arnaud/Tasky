# -*- coding: utf-8 -*-
"""
Version Dash / Cytoscape du planning.

Étapes actuelles :
- lecture de tasks_interactif.csv
- calcul des statuts (même logique que Planning.py)
- construction des nœuds / arêtes pour un graphe interactif
- app Dash avec :
  - affichage du graphe
  - surlignage interactif ancêtres / descendants
  - sauvegarde / rechargement de la position des nœuds
"""

import copy
import os
import csv
import json
from typing import Dict, List, Tuple

import dash
from dash import html, dcc, Input, Output, State, clientside_callback
import dash_cytoscape as cyto

# Layouts supplémentaires (dont "dagre", "cose-bilkent", etc.)
cyto.load_extra_layouts()


TASKS_CSV = os.path.join(os.path.dirname(__file__) or ".", "tasks.csv")
POSITIONS_JSON = os.path.join(os.path.dirname(__file__) or ".", "node_positions.json")

# Style de graphe (mêmes valeurs conceptuelles que dans Planning.py)
# - "groups" : groupement par pièce / location
# - "no goals" : suppression des objectifs (type "O") dans les groupes
# - "mess" : tout dans un seul groupe
GRAPH_STYLE = "groups"

# Palette de couleurs
# Sémantique : TODO=à faire, DONE=fait, READY=prêt à faire, URGENT=TOPRIO (chemin prioritaire), GOAL=PRIO/objectif
BG_COLOR = "#F5F3EE"

# Couleurs normales (fond des tâches)
COLOR_TODO = "#DDE6DA"
COLOR_DONE = "#E7E3DC"
COLOR_READY = "#A7B7C2"
COLOR_URGENT = "#A7B7C2"
COLOR_GOAL = "#C5BAD8"

# Couleurs de highlight (surlignage au clic : chaque nœud selon son statut réel)
COLOR_TODO_HL = "#7E8570"
COLOR_DONE_HL = "#B2B0AC"
COLOR_READY_HL = "#8FA1AB"
COLOR_URGENT_HL = "#8FA1AB"
COLOR_GOAL_HL = "#9B8FBF"

# Couleurs dédiées aux arêtes du surlignage (ancêtres vs descendants), pour garder la lecture du sens


def load_tasks_from_csv(path: str) -> Tuple[
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
    Dict[str, List[str]],
    Dict[str, List[str]],
]:
    """Charge les tâches depuis le CSV et remplit les dictionnaires."""
    types_dict: Dict[str, str] = {}
    status_dict: Dict[str, str] = {}
    location_dict: Dict[str, str] = {}
    desc_dict: Dict[str, str] = {}
    pred_dict: Dict[str, List[str]] = {}
    follow_dict: Dict[str, List[str]] = {}

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            i = row["id"].strip()
            if not i or not i.isdigit():
                continue
            types_dict[i] = row["type"].strip()
            status_dict[i] = row["status"].strip().upper()
            location_dict[i] = row["location"].strip()
            desc_dict[i] = i + ": " + row["description"].strip()
            pred_str = row["predecessors"].strip().replace(" ", "")
            # On accepte l'ancien séparateur ',' et le nouveau '-'
            cleaned = pred_str.replace(",", "-")
            pred_dict[i] = [p for p in cleaned.split("-") if p] if cleaned else []

    # Suivants : pour chaque tâche, liste des tâches qui en dépendent
    for k in pred_dict:
        follow_dict[k] = []
    for k in pred_dict:
        for pred_id in pred_dict[k]:
            if pred_id in follow_dict:
                follow_dict[pred_id].append(k)

    return types_dict, status_dict, location_dict, desc_dict, pred_dict, follow_dict


def compute_statuses(
    types_dict: Dict[str, str],
    status_dict: Dict[str, str],
    location_dict: Dict[str, str],
    pred_dict: Dict[str, List[str]],
    follow_dict: Dict[str, List[str]],
) -> Tuple[Dict[str, int], List[str]]:
    """
    Applique la logique de Planning.py pour ajuster les statuts,
    et retourne aussi le nombre de verrous (count_lockers) et le chemin de priorité.
    """
    count_lockers: Dict[str, int] = {}

    # For all Priority task, all previous not DONE become TOPRIO (except the priority ones)
    priority_paths_tasks: List[str] = []
    for t in [k for k, val in status_dict.items() if val == "PRIO"]:
        priority_paths_tasks.append(t)

        def set_prio(task_id: str) -> None:
            if status_dict[task_id] != "DONE":
                priority_paths_tasks.append(task_id)
                if status_dict[task_id] != "PRIO":
                    status_dict[task_id] = "TOPRIO"
                for p in pred_dict[task_id]:
                    set_prio(p)

        if len([p for p in pred_dict[t] if status_dict[p] != "DONE"]) == 0:
            priority_paths_tasks.append(t)
            status_dict[t] = "TOPRIO"
        else:
            for p in pred_dict[t]:
                set_prio(p)

    # Ajustement des statuts en fonction des prédécesseurs
    for k in status_dict.keys():
        count_lockers[k] = 0

        # Combien de prédécesseurs ne sont pas DONE ?
        for t in pred_dict[k]:
            if status_dict[t] not in ("DONE",):
                count_lockers[k] += 1

        if count_lockers[k] == 0:
            if status_dict[k] not in ["DONE", "TOPRIO"]:
                status_dict[k] = {"F": "Ready", "A": "ToBuy", "O": "DONE"}[types_dict[k]]
        else:
            if status_dict[k] in ["TOPRIO"]:
                status_dict[k] = "TODO"

    # Marquage des tâches critiques
    for k in follow_dict.keys():
        if len(follow_dict[k]) > 0:
            if status_dict[k] in ["Ready", "ToBuy"]:
                if min([count_lockers[a] for a in follow_dict[k]]) == 1:
                    status_dict[k] = status_dict[k] + "-" + "Critic"
        else:
            if status_dict[k] in ["Ready", "ToBuy"]:
                status_dict[k] = status_dict[k] + "-" + "Critic"

    return count_lockers, priority_paths_tasks


def build_cytoscape_elements(
    types_dict: Dict[str, str],
    status_dict: Dict[str, str],
    location_dict: Dict[str, str],
    desc_dict: Dict[str, str],
    pred_dict: Dict[str, List[str]],
    follow_dict: Dict[str, List[str]],
    count_lockers: Dict[str, int],
    priority_paths_tasks: List[str],
) -> List[dict]:
    """
    Construit la liste des éléments (nœuds + arêtes) pour dash_cytoscape.
    Gère aussi les groupes par location (compound nodes) quand GRAPH_STYLE == "groups"
    ou "no goals", en s'inspirant de Planning.py.
    """
    elements: List[dict] = []

    # --- Préparation des groupes par location (logique similaire à Planning.py) ---
    # Copie locale pour pouvoir la modifier sans casser meta
    grouped_location_dict: Dict[str, str] = dict(location_dict)

    if GRAPH_STYLE in ["mess", "no goals"]:
        # Un seul groupe "None"
        grouped_location_dict = {k: "None" for k in grouped_location_dict}

    # Pour les tâches de type "A" reliées à plusieurs pièces, on les met dans "None"
    for k, t_type in types_dict.items():
        if t_type == "A":
            followers_locations = {
                grouped_location_dict[o] for o in follow_dict.get(k, []) if o in grouped_location_dict
            }
            if len(followers_locations) != 1:
                grouped_location_dict[k] = "None"

    # Construction des groupes : location -> liste d'ids
    groups: Dict[str, List[str]] = {}
    for task_id, loc in grouped_location_dict.items():
        groups.setdefault(loc, []).append(task_id)

    # En mode "no goals", on retire les tâches de type "O" des groupes
    if GRAPH_STYLE in ["no goals"]:
        for loc, ids in list(groups.items()):
            groups[loc] = [i for i in ids if types_dict.get(i) != "O"]

    # --- Nœuds de groupe (compound nodes) ---
    for loc, ids in groups.items():
        if loc == "None":
            continue
        if not ids:
            continue
        group_id = f"group::{loc}"
        elements.append(
            {
                "data": {
                    "id": group_id,
                    "label": loc,
                    "is_group": "True",
                },
                # Par défaut, les groupes ne sont pas déplaçables ;
                # un toggle dans l'UI permet de les activer au besoin.
                "grabbable": False,
                "selectable": False,
            }
        )

    # --- Nœuds tâches ---
    for task_id in types_dict.keys():
        loc = grouped_location_dict[task_id]
        parent_id = None
        if loc != "None":
            parent_id = f"group::{loc}"

        data = {
            "id": task_id,
            "label": desc_dict[task_id],
            "status": status_dict[task_id],
            "type": types_dict[task_id],
            "location": loc,
            "count_lockers": count_lockers.get(task_id, 0),
            "priority_path": task_id in priority_paths_tasks,
        }
        if parent_id is not None:
            data["parent"] = parent_id

        elements.append({"data": data})

    # --- Arêtes (k -> t pour chaque suivant) ---
    for k, followers in follow_dict.items():
        for t in followers:
            loc_k = grouped_location_dict.get(k)
            loc_t = grouped_location_dict.get(t)

            # Logique équivalente à Planning.py pour masquer certains liens
            if GRAPH_STYLE in ["no goals"]:
                # On ne montre pas les liens impliquant des objectifs (type "O")
                if types_dict.get(k) == "O" or types_dict.get(t) == "O":
                    continue
                # Si les pièces sont différentes et que le bloquant est DONE,
                # on ne montre plus le lien
                if loc_k != loc_t and status_dict.get(k) == "DONE":
                    continue

            # Pour les liens entre pièces différentes en vue "groups",
            # on n'affiche le lien que si le bloquant n'est pas fini
            if loc_k != loc_t and status_dict.get(k) == "DONE":
                continue

            elements.append(
                {
                    "data": {
                        "id": f"{k}->{t}",
                        "source": k,
                        "target": t,
                        "source_done": status_dict.get(k) == "DONE",
                    }
                }
            )

    return elements


def build_model_from_csv(csv_path: str = TASKS_CSV) -> Tuple[List[dict], dict]:
    """
    Point d'entrée de haut niveau pour étapes 1 & 2.
    Retourne :
      - la liste des éléments Cytoscape (nœuds + arêtes)
      - un dict 'meta' avec les structures de base (utile pour les futures callbacks).
    """
    types_dict, status_dict, location_dict, desc_dict, pred_dict, follow_dict = load_tasks_from_csv(
        csv_path
    )
    count_lockers, priority_paths_tasks = compute_statuses(
        types_dict, status_dict, location_dict, pred_dict, follow_dict
    )
    elements = build_cytoscape_elements(
        types_dict,
        status_dict,
        location_dict,
        desc_dict,
        pred_dict,
        follow_dict,
        count_lockers,
        priority_paths_tasks,
    )

    # Si un fichier de positions existe, on l'applique aux nœuds
    if os.path.exists(POSITIONS_JSON):
        try:
            with open(POSITIONS_JSON, "r", encoding="utf-8") as f:
                saved_positions = json.load(f)
        except Exception:
            saved_positions = {}
        if isinstance(saved_positions, dict):
            for el in elements:
                data = el.get("data", {})
                node_id = data.get("id")
                if not node_id or "source" in data:
                    # on ne positionne que les nœuds, pas les arêtes
                    continue
                pos = saved_positions.get(node_id)
                if isinstance(pos, dict) and "x" in pos and "y" in pos:
                    el["position"] = {"x": pos["x"], "y": pos["y"]}

    meta = {
        "types_dict": types_dict,
        "status_dict": status_dict,
        "location_dict": location_dict,
        "desc_dict": desc_dict,
        "pred_dict": pred_dict,
        "follow_dict": follow_dict,
        "count_lockers": count_lockers,
        "priority_paths_tasks": priority_paths_tasks,
    }
    return elements, meta


def reload_meta_from_csv(csv_path: str = TASKS_CSV) -> dict:
    """Recharge les dictionnaires et recalcule les statuts sans reconstruire les éléments (pour mise à jour légère)."""
    types_dict, status_dict, location_dict, desc_dict, pred_dict, follow_dict = load_tasks_from_csv(
        csv_path
    )
    count_lockers, priority_paths_tasks = compute_statuses(
        types_dict, status_dict, location_dict, pred_dict, follow_dict
    )
    return {
        "types_dict": types_dict,
        "status_dict": status_dict,
        "location_dict": location_dict,
        "desc_dict": desc_dict,
        "pred_dict": pred_dict,
        "follow_dict": follow_dict,
        "count_lockers": count_lockers,
        "priority_paths_tasks": priority_paths_tasks,
    }


def _edge_visible_in_style(
    source: str, target: str, meta: dict
) -> bool:
    """True si l'arête source -> target doit être affichée selon GRAPH_STYLE (même logique que build_cytoscape_elements)."""
    types_dict = meta.get("types_dict", {})
    status_dict = meta.get("status_dict", {})
    location_dict = meta.get("location_dict", {})
    grouped = dict(location_dict)
    if GRAPH_STYLE in ["mess", "no goals"]:
        grouped = {k: "None" for k in grouped}
    for k, t_type in types_dict.items():
        if t_type == "A":
            follow_dict = meta.get("follow_dict", {})
            followers_locations = {
                grouped.get(o) for o in follow_dict.get(k, []) if o in grouped
            }
            if len(followers_locations) != 1:
                grouped[k] = "None"
    loc_k = grouped.get(source)
    loc_t = grouped.get(target)
    if GRAPH_STYLE in ["no goals"]:
        if types_dict.get(source) == "O" or types_dict.get(target) == "O":
            return False
        if loc_k != loc_t and status_dict.get(source) == "DONE":
            return False
    if loc_k != loc_t and status_dict.get(source) == "DONE":
        return False
    return True


def patch_elements_after_dependency_change(
    elements_state: list,
    add_edge: Tuple[str, str] | None,
    remove_edge: Tuple[str, str] | None,
    new_meta: dict,
) -> list:
    """
    Modifie la liste d'éléments en place : ajoute ou supprime une arête et met à jour
    les données des nœuds (count_lockers, priority_path, status). Préserve positions et ordre.
    """
    out = copy.deepcopy(elements_state or [])
    types_dict = new_meta.get("types_dict", {})
    status_dict = new_meta.get("status_dict", {})
    count_lockers = new_meta.get("count_lockers", {})
    priority_paths_tasks = new_meta.get("priority_paths_tasks", [])

    if remove_edge:
        source, target = remove_edge
        edge_id = f"{source}->{target}"
        out = [el for el in out if el.get("data", {}).get("id") != edge_id]

    if add_edge:
        source, target = add_edge
        if _edge_visible_in_style(source, target, new_meta):
            out.append(
                {
                    "data": {
                        "id": f"{source}->{target}",
                        "source": source,
                        "target": target,
                        "source_done": new_meta.get("status_dict", {}).get(source) == "DONE",
                    }
                }
            )

    for el in out:
        data = el.get("data", {})
        if "source" in data:
            continue
        node_id = data.get("id")
        if not node_id or data.get("is_group") == "True":
            continue
        data["status"] = status_dict.get(node_id, data.get("status", "TODO"))
        data["type"] = types_dict.get(node_id, data.get("type", "F"))
        data["count_lockers"] = count_lockers.get(node_id, 0)
        data["priority_path"] = node_id in priority_paths_tasks

    return out


def _collect_ancestors(
    start_id: str, pred_dict: Dict[str, List[str]], max_depth: int | None = None
) -> Tuple[List[str], List[str]]:
    """
    Retourne la liste des ancêtres (prédecesseurs récursifs) d'une tâche
    et la liste des arêtes (id "pred->child") parcourues.
    max_depth : nombre de niveaux à explorer (None = illimité).
    """
    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    stack: List[Tuple[str, int]] = [(start_id, 0)]

    while stack:
        node, depth = stack.pop()
        if max_depth is not None and depth >= max_depth:
            continue
        for pred in pred_dict.get(node, []):
            edge_id = f"{pred}->{node}"
            visited_edges.add(edge_id)
            if pred in visited_nodes:
                continue
            visited_nodes.add(pred)
            stack.append((pred, depth + 1))

    return list(visited_nodes), list(visited_edges)


def _collect_descendants(
    start_id: str, follow_dict: Dict[str, List[str]], max_depth: int | None = None
) -> Tuple[List[str], List[str]]:
    """
    Retourne la liste des descendants (suivants récursifs) d'une tâche
    et la liste des arêtes (id "parent->child") parcourues.
    max_depth : nombre de niveaux à explorer (None = illimité).
    """
    visited_nodes: set[str] = set()
    visited_edges: set[str] = set()
    stack: List[Tuple[str, int]] = [(start_id, 0)]

    while stack:
        node, depth = stack.pop()
        if max_depth is not None and depth >= max_depth:
            continue
        for child in follow_dict.get(node, []):
            edge_id = f"{node}->{child}"
            visited_edges.add(edge_id)
            if child in visited_nodes:
                continue
            visited_nodes.add(child)
            stack.append((child, depth + 1))

    return list(visited_nodes), list(visited_edges)


def save_csv_from_meta(meta: dict, csv_path: str = TASKS_CSV) -> None:
    """Reécrit le CSV entier depuis le meta-store (pour synchroniser après changements en mémoire)."""
    types_dict = meta.get("types_dict", {})
    status_dict = meta.get("status_dict", {})
    location_dict = meta.get("location_dict", {})
    desc_dict = meta.get("desc_dict", {})
    pred_dict = meta.get("pred_dict", {})
    all_ids = sorted(types_dict.keys(), key=lambda x: int(x) if x.isdigit() else 0)
    rows = []
    for i in all_ids:
        raw_desc = desc_dict.get(i, "")
        # desc_dict stores "id: description", strip the prefix
        if raw_desc.startswith(i + ": "):
            raw_desc = raw_desc[len(i) + 2:]
        rows.append({
            "id": i,
            "type": types_dict.get(i, ""),
            "status": status_dict.get(i, ""),
            "location": location_dict.get(i, ""),
            "description": raw_desc,
            "predecessors": "-".join(pred_dict.get(i, [])),
        })
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "type", "status", "location", "description", "predecessors"])
        writer.writeheader()
        writer.writerows(rows)


def update_predecessors_in_csv(
    csv_path: str, task_id: str, new_pred_list: List[str]
) -> None:
    """
    Met à jour la colonne 'predecessors' pour la tâche task_id dans le CSV.
    new_pred_list : liste d'ids de prédécesseurs (séparateur '-' à l'écriture).
    """
    rows: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or [
            "id", "type", "status", "location", "description", "predecessors"
        ]
        for row in reader:
            if row.get("id", "").strip() == str(task_id).strip():
                row["predecessors"] = "-".join(str(p).strip() for p in new_pred_list if p)
            rows.append(row)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _would_create_cycle(
    pred_dict: Dict[str, List[str]], new_pred: str, successor_id: str
) -> bool:
    """True si ajouter new_pred comme prédécesseur de successor_id créerait un cycle."""
    ancestors, _ = _collect_ancestors(new_pred, pred_dict, max_depth=None)
    return successor_id in ancestors


# --- App Dash minimale : affichage statique du graphe ---

elements, meta = build_model_from_csv()

# Si des positions sont présentes, on utilise le layout "preset" (positions figées).
# Sinon, on utilise un layout automatique.
has_preset_positions = any(
    ("position" in el) and ("source" not in el.get("data", {})) for el in elements
)

INITIAL_LAYOUT = (
    {"name": "preset"}
    if has_preset_positions
    else {
        "name": "cose-bilkent",
    }
)

# Feuille de style Cytoscape : règles visuelles de base
CYTOSCAPE_STYLESHEET: List[dict] = [
    {
        "selector": "node",
        "style": {
            "label": "data(label)",
            "font-size": "24px",
            "text-wrap": "wrap",
            # largeur max un peu augmentée pour éviter trop de coupures
            "text-max-width": "220px",
            "text-valign": "center",
            "text-halign": "center",
            "background-color": BG_COLOR,
            "border-width": 1,
            "border-color": "#555555",
            # dimensions adaptées au label + marge interne
            "width": "label",
            "height": "label",
            "padding": "16px",
        },
    },
    # Nœuds de groupe (pièces) : fond gris clair, titre en haut
    {
        "selector": 'node[is_group = "True"]',
        "style": {
            "shape": "round-rectangle",
            "background-color": BG_COLOR,
            "border-color": "#888888",
            "border-width": 2,
            "padding": "30px",
            "text-valign": "top",
            "text-halign": "center",
            "font-weight": "bold",
            "font-size": "48px",
            "events": "no",
        },
    },
    # Formes par type (approximation de ton Graphviz)
    {
        "selector": 'node[type = "A"]',
        "style": {"shape": "ellipse"},
    },
    {
        "selector": 'node[type = "F"]',
        "style": {"shape": "round-rectangle"},
    },
    {
        "selector": 'node[type = "O"]',
        "style": {
            "shape": "triangle",
            "background-color": COLOR_GOAL,
        },
    },
    # Couleurs par statut principal
    {"selector": 'node[status = "TODO"]', "style": {"background-color": COLOR_TODO}},
    {
        "selector": 'node[status = "PRIO"]',
        # Même couleur que les objectifs (rouge doux)
        "style": {"background-color": COLOR_GOAL},
    },
    {
        "selector": 'node[status = "TOPRIO"]',
        "style": {"background-color": COLOR_URGENT},
    },
    {"selector": 'node[status = "DONE"]', "style": {"background-color": COLOR_DONE, "opacity": 0.3}},
    {
        "selector": 'node[status *= "Ready"]',
        "style": {"background-color": COLOR_READY},
    },
    {
        "selector": 'node[status *= "ToBuy"]',
        "style": {"background-color": COLOR_READY},
    },
    # Mise en avant du chemin de priorité
    {
        "selector": 'node[?priority_path]',
        "style": {"border-width": 3, "border-color": "red"},
    },
    # Objectif PRIO : cerclage violet (écrase le rouge du chemin prioritaire)
    {
        "selector": 'node[status = "PRIO"]',
        "style": {"border-width": 3, "border-color": "#9B8FBF"},
    },
    {
        "selector": "node:selected",
        "style": {
            "border-width": 5,
            "border-color": "#0066FF",
            "border-style": "solid",
        },
    },
    {
        "selector": "edge:selected",
        "style": {
            "line-color": "#0066FF",
            "target-arrow-color": "#0066FF",
            "width": 7,
        },
    },
    {
        "selector": "edge.edge-selected",
        "style": {
            "line-color": "#0066FF",
            "target-arrow-color": "#0066FF",
            "width": 7,
        },
    },
    # Styles pour les arêtes
    {
        "selector": "edge",
        "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "line-color": "#999999",
            "target-arrow-color": "#999999",
            "width": 4,
        },
    },
    {
        "selector": "edge[?source_done]",
        "style": {"opacity": 0.3},
    },
]


app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.Div(
            [
                html.Button(
                    "Sauver les positions",
                    id="save-positions",
                    n_clicks=0,
                    style={"margin-right": "10px"},
                ),
                html.Button(
                    "Annuler",
                    id="undo-positions",
                    n_clicks=0,
                    style={"margin-right": "10px"},
                ),
                html.Button(
                    "Autosave : ON",
                    id="autosave-btn",
                    n_clicks=0,
                    style={"margin-right": "10px"},
                ),
                html.Button(
                    "Snap : ON",
                    id="snap-btn",
                    n_clicks=0,
                    title="Active/désactive le snap sur grille virtuelle",
                    style={"margin-right": "10px"},
                ),
                html.Span(id="save-status", style={"font-size": "12px", "margin-right": "15px"}),
            ],
            style={"margin": "5px 0 10px 0", "display": "flex", "alignItems": "center", "flexWrap": "wrap"},
        ),
        dcc.Store(id="meta-store", data=meta),
        dcc.Store(id="viewport-debug", data=None),
        dcc.Store(id="restore-viewport-trigger", data=None),
        dcc.Store(id="restore-viewport-done", data=0),
        dcc.Store(id="position-history", data=[]),
        dcc.Store(id="autosave-enabled", data=False),
        dcc.Interval(id="auto-save-interval", interval=10 * 1000, n_intervals=0),
        dcc.Interval(id="countdown-interval", interval=1000, n_intervals=0),
        dcc.Store(id="next-autosave-ts", data=0),
        cyto.Cytoscape(
            id="planning-graph",
            elements=elements,
            layout=INITIAL_LAYOUT,
            style={"width": "100%", "height": "800px", "border": "1px solid #ccc"},
            stylesheet=CYTOSCAPE_STYLESHEET,
            boxSelectionEnabled=True,
        ),
        html.Div(
            id="context-menu",
            style={
                "display": "none",
                "position": "fixed",
                "background": "white",
                "border": "1px solid #ccc",
                "borderRadius": "6px",
                "boxShadow": "2px 4px 12px rgba(0,0,0,0.18)",
                "zIndex": "1000",
                "minWidth": "190px",
                "padding": "4px 0",
                "fontSize": "14px",
                "userSelect": "none",
            },
        ),
        html.Button(id="ctx-confirm-btn", n_clicks=0, style={"display": "none"}),
        dcc.Store(id="ctx-action", data=None),
    ],
    style={"width": "100%", "height": "100vh", "padding": "10px", "backgroundColor": BG_COLOR},
)




@app.callback(
    Output("viewport-debug", "data"),
    [
        Input("planning-graph", "pan"),
        Input("planning-graph", "zoom"),
        Input("planning-graph", "extent"),
    ],
)
def store_viewport_debug(pan, zoom, extent):
    """Enregistre pan, zoom et extent envoyés par le graphe (pour debug / restauration viewport)."""
    return {"pan": pan, "zoom": zoom, "extent": extent}






# Restauration du viewport après ajout/suppression de dépendance (évite le zoom reset de dash-cytoscape).
# On restaure en réglant zoom et pan à partir de l'extent (coordonnées modèle).
# Sortie vers un Store factice pour éviter un bug du renderer Dash.
clientside_callback(
    """
    function(extentData) {
        try {
            if (extentData == null || typeof extentData !== 'object') return 0;
            var x1 = extentData.x1, x2 = extentData.x2, y1 = extentData.y1, y2 = extentData.y2;
            if (typeof x1 !== 'number' || typeof x2 !== 'number' || typeof y1 !== 'number' || typeof y2 !== 'number') return 0;
            var cy = (typeof window !== 'undefined') ? window.cy : null;
            if (!cy || typeof cy.zoom !== 'function' || typeof cy.pan !== 'function') return 0;
            var xMin = Math.min(x1, x2), xMax = Math.max(x1, x2), yMin = Math.min(y1, y2), yMax = Math.max(y1, y2);
            var boxW = xMax - xMin, boxH = yMax - yMin;
            if (boxW <= 0 || boxH <= 0) return 0;
            var pad = 50;
            function doRestore() {
                try {
                    if (!window.cy) return;
                    var c = window.cy;
                    var W = c.width(), H = c.height();
                    if (W <= 0 || H <= 0) return;
                    var zoom = Math.min((W - 2 * pad) / boxW, (H - 2 * pad) / boxH);
                    var centerX = (xMin + xMax) / 2, centerY = (yMin + yMax) / 2;
                    c.zoom(zoom);
                    c.pan({ x: W / 2 - centerX * zoom, y: H / 2 - centerY * zoom });
                } catch (e2) { console.warn('restore-viewport:', e2); }
            }
            setTimeout(doRestore, 250);
            setTimeout(doRestore, 500);
        } catch (e) { console.warn('restore-viewport:', e); }
        return 0;
    }
    """,
    Output("restore-viewport-done", "data"),
    Input("restore-viewport-trigger", "data"),
)


clientside_callback(
    """
    function(n_clicks) {
        var ctxMenu = document.getElementById('context-menu');

        function hideCtxMenu() { if (ctxMenu) ctxMenu.style.display = 'none'; }
        function selectEdge(el) {
            el.addClass('edge-selected');
            el.style({'line-color': '#0066FF', 'target-arrow-color': '#0066FF', 'width': 7});
        }
        function deselectEdge(el) {
            el.removeClass('edge-selected');
            el.removeStyle('line-color');
            el.removeStyle('target-arrow-color');
            el.removeStyle('width');
        }
        function clearEdgeSelection() {
            window.cy.edges('.edge-selected').each(function(e) { deselectEdge(e); });
        }

        function registerHandlers() {
            if (!window.cy || window._cyHandlersRegistered) return;
            window._cyHandlersRegistered = true;

            // --- Snap on dragfree ---
            window._snapEnabled = true;
            window._snapGridSize = 40;
            window.cy.on('dragfree', 'node', function(evt) {
                if (!window._snapEnabled) return;
                var node = evt.target;
                if (node.data('is_group') === 'True') return;
                var pos = node.position();
                node.position({
                    x: Math.round(pos.x / window._snapGridSize) * window._snapGridSize,
                    y: Math.round(pos.y / window._snapGridSize) * window._snapGridSize
                });
            });

            // --- Toggle-select nœuds ---
            window._hoverEl = null;
            window.cy.on('mouseover', 'node, edge', function(evt) {
                var el = evt.target;
                var sel = el.isEdge() ? el.hasClass('edge-selected') : el.selected();
                window._hoverEl = {id: el.id(), selected: sel};
            });
            window.cy.on('tap', 'node', function(evt) {
                hideCtxMenu();
                var isShift = evt.originalEvent && evt.originalEvent.shiftKey;
                var wasSelected = window._hoverEl &&
                                  window._hoverEl.id === evt.target.id() &&
                                  window._hoverEl.selected;
                if (!isShift && wasSelected) evt.target.unselect();
            });

            // --- Toggle-select arêtes ---
            window.cy.on('tap', 'edge', function(evt) {
                hideCtxMenu();
                var isShift = evt.originalEvent && evt.originalEvent.shiftKey;
                var el = evt.target;
                var wasSelected = window._hoverEl &&
                                  window._hoverEl.id === el.id() &&
                                  window._hoverEl.selected;
                if (!isShift) {
                    clearEdgeSelection();
                    if (!wasSelected) selectEdge(el);
                } else {
                    if (wasSelected) deselectEdge(el);
                    else selectEdge(el);
                }
            });

            // Clic sur fond : effacer sélection + menu
            window.cy.on('tap', function(evt) {
                if (evt.target === window.cy) { clearEdgeSelection(); hideCtxMenu(); }
            });

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') hideCtxMenu();
            });

            // --- Menu contextuel (clic droit) ---
            window.cy.on('cxttap', function(evt) {
                evt.originalEvent.preventDefault();
                var target = evt.target;
                var isBg = (target === window.cy);

                if (!isBg) {
                    if (target.isEdge()) selectEdge(target);
                    else target.select();
                }

                var selEdges = window.cy.edges('.edge-selected');
                var selNodes = window.cy.$(":selected").filter("node").not('[is_group = "True"]');
                var edgeIds = selEdges.map(function(e){ return e.id(); });
                var nodeIds = selNodes.map(function(n){ return n.id(); });

                var items = [];
                if (edgeIds.length > 0) {
                    var lbl = edgeIds.length === 1 ? "Supprimer ce lien" : "Supprimer " + edgeIds.length + " liens";
                    items.push({action: "delete_edges", label: "🗑 " + lbl, edge_ids: edgeIds, node_ids: nodeIds});
                }

                if (items.length === 0) { hideCtxMenu(); return; }

                var x = evt.originalEvent.clientX, y = evt.originalEvent.clientY;
                ctxMenu.innerHTML = '';
                items.forEach(function(item) {
                    var el = document.createElement('div');
                    el.textContent = item.label;
                    el.style.cssText = 'padding:9px 18px;cursor:pointer;white-space:nowrap;';
                    el.onmouseenter = function(){ el.style.background = '#f0f0f0'; };
                    el.onmouseleave = function(){ el.style.background = ''; };
                    el.onclick = function() {
                        window._ctxAction = {action: item.action, edge_ids: item.edge_ids, node_ids: item.node_ids};
                        document.getElementById('ctx-confirm-btn').click();
                        hideCtxMenu();
                    };
                    ctxMenu.appendChild(el);
                });
                ctxMenu.style.left = x + 'px';
                ctxMenu.style.top = y + 'px';
                ctxMenu.style.display = 'block';
                setTimeout(function() {
                    var r = ctxMenu.getBoundingClientRect();
                    if (r.right > window.innerWidth) ctxMenu.style.left = (x - r.width) + 'px';
                    if (r.bottom > window.innerHeight) ctxMenu.style.top = (y - r.height) + 'px';
                }, 0);
            });
        }

        // Enregistre les handlers dès que cy est prêt (avec retries si pas encore initialisé)
        registerHandlers();
        if (!window._cyHandlersRegistered) {
            setTimeout(registerHandlers, 300);
            setTimeout(registerHandlers, 800);
        }

        if (!n_clicks) return "Snap : ON";
        window._snapEnabled = !window._snapEnabled;
        return window._snapEnabled ? "Snap : ON" : "Snap : OFF";
    }
    """,
    Output("snap-btn", "children"),
    Input("snap-btn", "n_clicks"),
)

clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks || !window._ctxAction) return window.dash_clientside.no_update;
        var action = window._ctxAction;
        window._ctxAction = null;
        return action;
    }
    """,
    Output("ctx-action", "data"),
    Input("ctx-confirm-btn", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) return [false, "Autosave : OFF"];
        var enabled = n_clicks % 2 !== 0;
        return [enabled, enabled ? "Autosave : ON" : "Autosave : OFF"];
    }
    """,
    [Output("autosave-enabled", "data"), Output("autosave-btn", "children")],
    Input("autosave-btn", "n_clicks"),
)

clientside_callback(
    "function(n) { return Date.now() + 10000; }",
    Output("next-autosave-ts", "data"),
    Input("auto-save-interval", "n_intervals"),
)

clientside_callback(
    """
    function(n, nextTs, enabled) {
        if (!enabled) return "Sauver les positions";
        if (!nextTs) return "Sauver les positions";
        var remaining = Math.max(0, Math.round((nextTs - Date.now()) / 1000));
        return "Sauver (auto " + remaining + "s)";
    }
    """,
    Output("save-positions", "children"),
    Input("countdown-interval", "n_intervals"),
    [State("next-autosave-ts", "data"), State("autosave-enabled", "data")],
)


def _extract_positions(elements_state: list) -> Dict[str, Dict[str, float]]:
    """Extrait les positions des nœuds depuis la liste d'éléments Cytoscape."""
    positions: Dict[str, Dict[str, float]] = {}
    if not elements_state:
        return positions
    for el in elements_state:
        data = el.get("data", {})
        if "source" in data or "target" in data:
            continue
        node_id = data.get("id")
        if not node_id:
            continue
        pos = el.get("position")
        if not isinstance(pos, dict):
            continue
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            continue
        positions[node_id] = {"x": float(x), "y": float(y)}
    return positions


def _apply_positions_to_elements(
    elements_state: list, positions: Dict[str, Dict[str, float]]
) -> list:
    """Retourne une copie des éléments avec les positions remplacées (ou supprimées si positions vide)."""
    out = copy.deepcopy(elements_state)
    for el in out:
        data = el.get("data", {})
        if "source" in data or "target" in data:
            continue
        node_id = data.get("id")
        if not node_id:
            continue
        if node_id in positions:
            p = positions[node_id]
            el["position"] = {"x": p["x"], "y": p["y"]}
        else:
            el.pop("position", None)
    return out


@app.callback(
    [Output("save-status", "children"), Output("position-history", "data")],
    Input("save-positions", "n_clicks"),
    [State("planning-graph", "elements"), State("position-history", "data"), State("meta-store", "data")],
    prevent_initial_call=True,
)
def save_positions(n_clicks, elements_state, history, meta_data):
    """
    Sauvegarde les positions (JSON) et les données (CSV) puis ajoute à l'historique (pour Annuler).
    """
    if not n_clicks:
        return dash.no_update, dash.no_update

    positions = _extract_positions(elements_state or [])
    if not positions:
        return "Aucune position à sauvegarder.", history or []

    try:
        with open(POSITIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
        if meta_data:
            save_csv_from_meta(meta_data)
    except Exception as exc:
        return f"Erreur lors de la sauvegarde : {exc}", history or []

    new_history = (history or []) + [positions]
    if len(new_history) > 10:
        new_history = new_history[-10:]
    return f"{len(positions)} positions sauvegardées.", new_history


@app.callback(
    [Output("planning-graph", "elements", allow_duplicate=True), Output("save-status", "children", allow_duplicate=True), Output("position-history", "data", allow_duplicate=True)],
    Input("undo-positions", "n_clicks"),
    [State("position-history", "data"), State("planning-graph", "elements")],
    prevent_initial_call=True,
)
def undo_positions(n_clicks, history, elements_state):
    """
    Annule la dernière sauvegarde : restaure les positions précédentes et met à jour le graphe.
    """
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update
    if not history:
        return dash.no_update, "Rien à annuler (aucune sauvegarde).", dash.no_update

    new_history = history[:-1]
    restore = new_history[-1] if new_history else {}

    try:
        with open(POSITIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(restore, f, indent=2)
    except Exception as exc:
        return dash.no_update, f"Erreur annulation : {exc}", dash.no_update

    new_elements = _apply_positions_to_elements(elements_state or [], restore)
    return new_elements, "Positions restaurées (annulation).", new_history



@app.callback(
    Output("save-status", "children", allow_duplicate=True),
    Input("auto-save-interval", "n_intervals"),
    [State("planning-graph", "elements"), State("autosave-enabled", "data"), State("meta-store", "data")],
    prevent_initial_call=True,
)
def auto_save_positions(n_intervals, elements_state, autosave_enabled, meta_data):
    """Sauvegarde automatique des positions (JSON) et des données (CSV) toutes les 10 secondes."""
    if n_intervals == 0 or not autosave_enabled:
        return dash.no_update
    positions = _extract_positions(elements_state or [])
    if not positions:
        return dash.no_update
    try:
        with open(POSITIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
        if meta_data:
            save_csv_from_meta(meta_data)
    except Exception:
        pass
    return dash.no_update


@app.callback(
    [
        Output("planning-graph", "elements", allow_duplicate=True),
        Output("meta-store", "data", allow_duplicate=True),
        Output("restore-viewport-trigger", "data", allow_duplicate=True),
    ],
    Input("ctx-action", "data"),
    [State("planning-graph", "elements"), State("meta-store", "data"), State("viewport-debug", "data")],
    prevent_initial_call=True,
)
def handle_context_action(action_data, elements_state, meta_data, viewport_debug):
    if not action_data:
        return dash.no_update, dash.no_update, dash.no_update
    action = action_data.get("action")
    m = meta_data if meta_data is not None else meta

    if action == "delete_edges":
        edge_ids = action_data.get("edge_ids", [])
        if not edge_ids:
            return dash.no_update, dash.no_update, dash.no_update
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        for edge_id in edge_ids:
            if "->" in edge_id:
                source, target = edge_id.split("->", 1)
                preds = pred_dict.get(target, [])
                if source in preds:
                    pred_dict[target] = [p for p in preds if p != source]
        # Recalcul du follow_dict et des statuts en mémoire (sans écrire le CSV)
        follow_dict: dict = {k: [] for k in pred_dict}
        for k, preds in pred_dict.items():
            for p in preds:
                if p in follow_dict:
                    follow_dict[p].append(k)
        types_dict = m.get("types_dict", {})
        status_dict = m.get("status_dict", {})
        location_dict = m.get("location_dict", {})
        desc_dict = m.get("desc_dict", {})
        count_lockers, priority_paths_tasks = compute_statuses(types_dict, status_dict, location_dict, pred_dict, follow_dict)
        new_meta = {
            "types_dict": types_dict,
            "status_dict": status_dict,
            "location_dict": location_dict,
            "desc_dict": desc_dict,
            "pred_dict": pred_dict,
            "follow_dict": follow_dict,
            "count_lockers": count_lockers,
            "priority_paths_tasks": priority_paths_tasks,
        }
        edge_ids_set = set(edge_ids)
        new_elements = [el for el in (elements_state or []) if el.get("data", {}).get("id") not in edge_ids_set]
        new_elements = patch_elements_after_dependency_change(new_elements, None, None, new_meta)
        extent = (viewport_debug or {}).get("extent")
        return new_elements, new_meta, extent

    return dash.no_update, dash.no_update, dash.no_update


if __name__ == "__main__":
    # Lancement du serveur Dash (Dash >= 3 : run_server est obsolète)
    app.run(debug=True)
