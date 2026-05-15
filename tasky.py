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
from collections import defaultdict
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
COLOR_TODO = "#E7E3DC"
COLOR_DONE = "#DDE6DA"
COLOR_READY = "#EDE4BE"
COLOR_URGENT = "#A7B7C2"
COLOR_GOAL = "#F0D2CF"

# Couleurs de highlight (surlignage au clic : chaque nœud selon son statut réel)
COLOR_TODO_HL = "#B2B0AC"
COLOR_DONE_HL = "#7E8570"
COLOR_READY_HL = "#D6C27A"
COLOR_URGENT_HL = "#8FA1AB"
COLOR_GOAL_HL = "#C9A3A1"

# Couleurs dédiées aux arêtes du surlignage (ancêtres vs descendants), pour garder la lecture du sens
COLOR_EDGE_ANCESTORS = "#8FA1AB"   # teinte bleue pour "en amont"
COLOR_EDGE_DESCENDANTS = "#7E8570"  # teinte verte pour "en aval"


def _highlight_color_for_status(status: str, task_type: str) -> str:
    """Retourne la couleur de fond highlight (_HL) selon le statut calculé et le type de la tâche."""
    if task_type == "O":
        return COLOR_GOAL_HL
    if status == "DONE":
        return COLOR_DONE_HL
    if "Ready" in status or "ToBuy" in status:
        return COLOR_READY_HL
    if status == "TOPRIO":
        return COLOR_URGENT_HL
    if status == "PRIO":
        return COLOR_GOAL_HL
    return COLOR_TODO_HL


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
                    }
                }
            )

    for el in out:
        data = el.get("data", {})
        if "source" in data:
            continue
        node_id = data.get("id")
        if not node_id:
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
            "font-size": "16px",
            # Les groupes ne capturent pas les événements souris : le drag sert à panner la vue.
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
    {"selector": 'node[status = "DONE"]', "style": {"background-color": COLOR_DONE}},
    {
        "selector": 'node[status *= "Ready"]',
        "style": {"background-color": COLOR_READY},
    },
    {
        "selector": 'node[status *= "ToBuy"]',
        "style": {"background-color": COLOR_READY},
    },
    # Tâches critiques : contour plus épais
    {
        "selector": 'node[status *= "Critic"]',
        "style": {"border-width": 3, "border-color": "red"},
    },
    # Mise en avant du chemin de priorité
    {
        "selector": 'node[priority_path = "True"]',
        "style": {"border-width": 3, "border-color": "orange"},
    },
    # Sélection multiple (Shift + rectangle) : contour visible, pas d’overlay pour garder les couleurs
    {
        "selector": "node:selected",
        "style": {
            "border-width": 5,
            "border-color": "#333",
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
]


app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.Div(
            [
                html.Label("Profondeur de surlignage : ", style={"margin-right": "5px"}),
                dcc.Dropdown(
                    id="depth-selector",
                    options=[
                        {"label": "1 niveau", "value": 1},
                        {"label": "2 niveaux", "value": 2},
                        {"label": "3 niveaux", "value": 3},
                        {"label": "Tous", "value": 0},
                    ],
                    value=1,
                    clearable=False,
                    style={"width": "160px", "display": "inline-block", "margin-right": "20px"},
                ),
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
                html.Span(id="save-status", style={"font-size": "12px", "margin-right": "15px"}),
                html.Div(
                    id="node-tooltip",
                    style={
                        "display": "inline-block",
                        "minHeight": "28px",
                        "padding": "6px 10px",
                        "marginLeft": "10px",
                        "backgroundColor": "#fff",
                        "border": "1px solid #888",
                        "borderRadius": "4px",
                        "fontSize": "14px",
                    },
                ),
            ],
            style={"margin": "5px 0 10px 0", "display": "flex", "alignItems": "center", "flexWrap": "wrap"},
        ),
        html.Div(
            [
                html.Label("Dépendances : ", style={"margin-right": "8px"}),
                dcc.Dropdown(
                    id="add-pred-dropdown",
                    placeholder="Prédécesseur à ajouter (sélectionnez une tâche ci‑dessus)",
                    clearable=True,
                    style={"width": "280px", "display": "inline-block", "margin-right": "8px"},
                ),
                html.Button(
                    "Ajouter dépendance",
                    id="add-dependency-btn",
                    n_clicks=0,
                    style={"margin-right": "10px"},
                ),
                html.Button(
                    "Supprimer la dépendance",
                    id="remove-dependency-btn",
                    n_clicks=0,
                    style={"margin-right": "10px"},
                ),
                html.Span(id="dependency-status", style={"font-size": "12px"}),
            ],
            style={"margin": "5px 0 10px 0", "display": "flex", "alignItems": "center", "flexWrap": "wrap"},
        ),
        dcc.Store(id="selected-node-id", data=None),
        dcc.Store(id="selected-edge-data", data=None),
        dcc.Store(id="meta-store", data=meta),
        dcc.Store(id="viewport-debug", data=None),
        dcc.Store(id="restore-viewport-trigger", data=None),
        dcc.Store(id="restore-viewport-done", data=0),
        dcc.Store(id="position-history", data=[]),
        dcc.Interval(id="auto-save-interval", interval=10 * 1000, n_intervals=0),
        cyto.Cytoscape(
            id="planning-graph",
            elements=elements,
            layout=INITIAL_LAYOUT,
            style={"width": "100%", "height": "800px", "border": "1px solid #ccc"},
            stylesheet=CYTOSCAPE_STYLESHEET,
            boxSelectionEnabled=True,
        ),
    ],
    style={"width": "100%", "height": "100vh", "padding": "10px", "backgroundColor": BG_COLOR},
)


@app.callback(
    Output("selected-node-id", "data"),
    Input("planning-graph", "tapNodeData"),
    State("selected-node-id", "data"),
)
def toggle_selected_node(tap_node_data, selected_node_id):
    """
    Clic sur une tâche : sélectionne la tâche. Recliquer sur la même tâche : déselectionne.
    Clic sur un groupe : déselectionne.
    """
    if not tap_node_data or not isinstance(tap_node_data, dict):
        return selected_node_id
    if tap_node_data.get("is_group") == "True":
        return None
    node_id = tap_node_data.get("id")
    if not node_id:
        return selected_node_id
    if node_id == selected_node_id:
        return None
    return node_id


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


@app.callback(
    Output("node-tooltip", "children"),
    Input("selected-node-id", "data"),
    [State("meta-store", "data"), State("viewport-debug", "data")],
)
def show_node_info(selected_node_id, meta_data, viewport_debug):
    """Affiche pour la tâche sélectionnée : ID, statut calculé, et pan/zoom/extent (debug)."""
    m = meta_data if meta_data is not None else meta
    if not selected_node_id:
        return "Cliquez sur une tâche pour voir son ID et son statut calculé."
    status = m.get("status_dict", {}).get(selected_node_id, "?")
    line = f"ID: {selected_node_id} — Statut calculé: {status}"
    if viewport_debug:
        parts = []
        if viewport_debug.get("pan") is not None:
            p = viewport_debug["pan"]
            if isinstance(p, dict):
                parts.append(f"Pan: x={p.get('x')}, y={p.get('y')}")
            else:
                parts.append(f"Pan: {p}")
        if viewport_debug.get("zoom") is not None:
            parts.append(f"Zoom: {viewport_debug['zoom']}")
        if viewport_debug.get("extent") is not None:
            e = viewport_debug["extent"]
            if isinstance(e, dict):
                parts.append(
                    f"Extent: x1={e.get('x1')}, y1={e.get('y1')}, x2={e.get('x2')}, y2={e.get('y2')}"
                )
            else:
                parts.append(f"Extent: {e}")
        if parts:
            line += " | " + " — ".join(parts)
    return line


@app.callback(
    Output("planning-graph", "stylesheet"),
    Input("selected-node-id", "data"),
    Input("depth-selector", "value"),
    State("meta-store", "data"),
)
def highlight_ancestors_descendants(selected_id, depth_value, meta_data):
    """
    Met à jour la feuille de style pour surligner :
    - le nœud sélectionné (bord noir + couleur _HL selon statut)
    - ses ancêtres et descendants (couleur _HL selon statut de chaque tâche).
    Si aucune tâche sélectionnée (décliqué), retour au stylesheet de base.
    """
    stylesheet = list(CYTOSCAPE_STYLESHEET)
    m = meta_data if meta_data is not None else meta

    if not selected_id or selected_id.startswith("group::"):
        return stylesheet

    # 0 = "Tous" (illimité), sinon 1 / 2 / 3 niveaux
    max_depth = None if depth_value == 0 else (depth_value or 1)

    ancestors, anc_edges = _collect_ancestors(selected_id, m["pred_dict"], max_depth)
    descendants, desc_edges = _collect_descendants(
        selected_id, m["follow_dict"], max_depth
    )

    # Nœud cliqué : bord noir + fond _HL selon son statut réel (une seule fonction pour tout)
    selected_status = m["status_dict"].get(selected_id, "TODO")
    selected_type = m["types_dict"].get(selected_id, "F")
    selected_bg = _highlight_color_for_status(selected_status, selected_type)
    stylesheet.append(
        {
            "selector": f'node[id = "{selected_id}"]',
            "style": {
                "border-width": 5,
                "border-color": "black",
                "background-color": selected_bg,
            },
        }
    )

    # Ancêtres : chaque nœud avec sa couleur _HL selon son statut (pas une seule couleur pour tous)
    anc_by_color: Dict[str, List[str]] = defaultdict(list)
    for aid in ancestors:
        st = m["status_dict"].get(aid, "TODO")
        ty = m["types_dict"].get(aid, "F")
        anc_by_color[_highlight_color_for_status(st, ty)].append(aid)
    for color, ids in anc_by_color.items():
        sel = ", ".join(f'node[id = "{i}"]' for i in ids)
        stylesheet.append(
            {
                "selector": sel,
                "style": {
                    "border-width": 4,
                    "border-color": color,
                    "background-color": color,
                },
            }
        )
    if anc_edges:
        sel_edges = ", ".join(f'edge[id = "{e}"]' for e in anc_edges)
        stylesheet.append(
            {
                "selector": sel_edges,
                "style": {
                    "width": 6,
                    "line-color": COLOR_EDGE_ANCESTORS,
                    "target-arrow-color": COLOR_EDGE_ANCESTORS,
                },
            }
        )

    # Descendants : chaque nœud avec sa couleur _HL selon son statut
    desc_by_color: Dict[str, List[str]] = defaultdict(list)
    for did in descendants:
        st = m["status_dict"].get(did, "TODO")
        ty = m["types_dict"].get(did, "F")
        desc_by_color[_highlight_color_for_status(st, ty)].append(did)
    for color, ids in desc_by_color.items():
        sel = ", ".join(f'node[id = "{i}"]' for i in ids)
        stylesheet.append(
            {
                "selector": sel,
                "style": {
                    "border-width": 4,
                    "border-color": color,
                    "background-color": color,
                },
            }
        )
    if desc_edges:
        sel_edges = ", ".join(f'edge[id = "{e}"]' for e in desc_edges)
        stylesheet.append(
            {
                "selector": sel_edges,
                "style": {
                    "width": 6,
                    "line-color": COLOR_EDGE_DESCENDANTS,
                    "target-arrow-color": COLOR_EDGE_DESCENDANTS,
                },
            }
        )

    return stylesheet


@app.callback(
    [Output("add-pred-dropdown", "options"), Output("add-pred-dropdown", "value")],
    Input("selected-node-id", "data"),
    State("meta-store", "data"),
)
def update_add_pred_dropdown(selected_node_id, meta_data):
    """Remplit le dropdown des prédécesseurs possibles pour la tâche sélectionnée."""
    m = meta_data if meta_data is not None else meta
    pred_dict = m.get("pred_dict", {})
    desc_dict = m.get("desc_dict", {})
    types_dict = m.get("types_dict", {})
    all_ids = list(types_dict.keys())
    if not selected_node_id or selected_node_id.startswith("group::"):
        return [], None
    existing_preds = set(pred_dict.get(selected_node_id, []))
    options = [
        {"label": f"{tid} — {desc_dict.get(tid, tid)[:50]}", "value": tid}
        for tid in sorted(all_ids, key=lambda x: int(x) if x.isdigit() else 0)
        if tid != selected_node_id and tid not in existing_preds
    ]
    return options, None


@app.callback(
    Output("selected-edge-data", "data"),
    Input("planning-graph", "tapEdgeData"),
)
def store_selected_edge(tap_edge_data):
    """Mémorise l'arête cliquée (pour suppression de dépendance)."""
    if not tap_edge_data or not isinstance(tap_edge_data, dict):
        return None
    return tap_edge_data


@app.callback(
    [
        Output("planning-graph", "elements", allow_duplicate=True),
        Output("meta-store", "data", allow_duplicate=True),
        Output("dependency-status", "children"),
        Output("add-pred-dropdown", "value", allow_duplicate=True),
        Output("restore-viewport-trigger", "data", allow_duplicate=True),
    ],
    Input("add-dependency-btn", "n_clicks"),
    [
        State("selected-node-id", "data"),
        State("add-pred-dropdown", "value"),
        State("planning-graph", "elements"),
        State("viewport-debug", "data"),
        State("meta-store", "data"),
    ],
    prevent_initial_call=True,
)
def add_dependency(n_clicks, selected_node_id, new_pred_id, elements_state, viewport_debug, meta_data):
    """Ajoute un prédécesseur à la tâche sélectionnée et met à jour le CSV."""
    if not n_clicks or not selected_node_id or not new_pred_id:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    m = meta_data if meta_data is not None else meta
    pred_dict = m.get("pred_dict", {})
    if _would_create_cycle(pred_dict, new_pred_id, selected_node_id):
        return (
            dash.no_update,
            dash.no_update,
            f"Impossible : créerait un cycle (la tâche {selected_node_id} est déjà en aval de {new_pred_id}).",
            dash.no_update,
            dash.no_update,
        )
    new_pred_list = list(pred_dict.get(selected_node_id, [])) + [new_pred_id]
    try:
        update_predecessors_in_csv(TASKS_CSV, selected_node_id, new_pred_list)
    except Exception as exc:
        return (
            dash.no_update,
            dash.no_update,
            f"Erreur écriture CSV : {exc}",
            dash.no_update,
            dash.no_update,
        )
    new_meta = reload_meta_from_csv(TASKS_CSV)
    new_elements = patch_elements_after_dependency_change(
        elements_state, add_edge=(new_pred_id, selected_node_id), remove_edge=None, new_meta=new_meta
    )
    extent = (viewport_debug or {}).get("extent") if viewport_debug else None
    return new_elements, new_meta, f"Dépendance {new_pred_id} → {selected_node_id} ajoutée.", None, extent


@app.callback(
    [
        Output("planning-graph", "elements", allow_duplicate=True),
        Output("meta-store", "data", allow_duplicate=True),
        Output("dependency-status", "children", allow_duplicate=True),
        Output("selected-edge-data", "data", allow_duplicate=True),
        Output("restore-viewport-trigger", "data", allow_duplicate=True),
    ],
    Input("remove-dependency-btn", "n_clicks"),
    [
        State("selected-edge-data", "data"),
        State("planning-graph", "elements"),
        State("viewport-debug", "data"),
        State("meta-store", "data"),
    ],
    prevent_initial_call=True,
)
def remove_dependency(n_clicks, edge_data, elements_state, viewport_debug, meta_data):
    """Supprime la dépendance correspondant à l'arête sélectionnée et met à jour le CSV."""
    if not n_clicks or not edge_data:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    source = edge_data.get("source")
    target = edge_data.get("target")
    if not source or not target:
        return dash.no_update, dash.no_update, "Sélectionnez une arête (clic sur un lien).", dash.no_update, dash.no_update
    m = meta_data if meta_data is not None else meta
    pred_dict = m.get("pred_dict", {})
    current = list(pred_dict.get(target, []))
    if source not in current:
        return dash.no_update, dash.no_update, f"La dépendance {source} → {target} n'existe pas.", dash.no_update, dash.no_update
    new_pred_list = [p for p in current if p != source]
    try:
        update_predecessors_in_csv(TASKS_CSV, target, new_pred_list)
    except Exception as exc:
        return (
            dash.no_update,
            dash.no_update,
            f"Erreur écriture CSV : {exc}",
            dash.no_update,
            dash.no_update,
        )
    new_meta = reload_meta_from_csv(TASKS_CSV)
    new_elements = patch_elements_after_dependency_change(
        elements_state, add_edge=None, remove_edge=(source, target), new_meta=new_meta
    )
    extent = (viewport_debug or {}).get("extent") if viewport_debug else None
    return new_elements, new_meta, f"Dépendance {source} → {target} supprimée.", None, extent


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
    [State("planning-graph", "elements"), State("position-history", "data")],
    prevent_initial_call=True,
)
def save_positions(n_clicks, elements_state, history):
    """
    Sauvegarde les positions dans le fichier JSON et les ajoute à l'historique (pour Annuler).
    """
    if not n_clicks:
        return dash.no_update, dash.no_update

    positions = _extract_positions(elements_state or [])
    if not positions:
        return "Aucune position à sauvegarder.", history or []

    try:
        with open(POSITIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
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
    State("planning-graph", "elements"),
    prevent_initial_call=True,
)
def auto_save_positions(n_intervals, elements_state):
    """Sauvegarde automatique des positions toutes les 10 secondes."""
    if n_intervals == 0:
        return dash.no_update
    positions = _extract_positions(elements_state or [])
    if not positions:
        return dash.no_update
    try:
        with open(POSITIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2)
    except Exception:
        pass
    return dash.no_update


if __name__ == "__main__":
    # Lancement du serveur Dash (Dash >= 3 : run_server est obsolète)
    app.run(debug=True)
