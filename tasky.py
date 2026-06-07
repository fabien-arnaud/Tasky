# -*- coding: utf-8 -*-

VERSION = "2.0.037"

import copy
import os
import csv
import io
import json
import shutil
from typing import Dict, List, Tuple

import dash
from dash import html, dcc, Input, Output, State, clientside_callback
import dash_cytoscape as cyto

# Layouts supplémentaires (dont "dagre", "cose-bilkent", etc.)
cyto.load_extra_layouts()



class LocalVersionedStorage:
    """Lecture/écriture locale avec historique versionné (undo jusqu'à MAX_VERSIONS)."""

    MAX_VERSIONS = 100

    def __init__(self):
        self.data_dir = os.environ.get(
            "DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        )
        self.history_dir = os.path.join(self.data_dir, "history")
        os.makedirs(self.history_dir, exist_ok=True)
        self._seed_from_example()
        if self._get_head() == 0:
            self._save_snapshot()

    def _seed_from_example(self):
        tasks_path = os.path.join(self.data_dir, "tasks.csv")
        if not os.path.exists(tasks_path):
            example = os.path.join(self.data_dir, "tasks.example.csv")
            if os.path.exists(example):
                shutil.copy2(example, tasks_path)
        positions_path = os.path.join(self.data_dir, "node_positions.json")
        if not os.path.exists(positions_path):
            with open(positions_path, "w", encoding="utf-8") as f:
                f.write("{}")

    def _head_path(self):
        return os.path.join(self.history_dir, ".head")

    def _get_head(self):
        try:
            return int(open(self._head_path()).read().strip())
        except Exception:
            return 0

    def _set_head(self, n):
        with open(self._head_path(), "w") as f:
            f.write(str(n))

    def _snap_dir(self, n):
        return os.path.join(self.history_dir, f"{n:06d}")

    def _all_versions(self):
        versions = []
        for e in os.listdir(self.history_dir):
            if not e.startswith("."):
                try:
                    versions.append(int(e))
                except ValueError:
                    pass
        return sorted(versions)

    def read_text(self, filename: str) -> str:
        with open(os.path.join(self.data_dir, filename), "r", encoding="utf-8") as f:
            return f.read()

    def write_text(self, filename: str, content: str, **kwargs) -> None:
        with open(os.path.join(self.data_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)
        self._save_snapshot()

    def _save_snapshot(self):
        head = self._get_head()
        new_head = head + 1
        for n in self._all_versions():
            if n > head:
                shutil.rmtree(self._snap_dir(n), ignore_errors=True)
        snap = self._snap_dir(new_head)
        os.makedirs(snap, exist_ok=True)
        for fname in ("tasks.csv", "node_positions.json"):
            src = os.path.join(self.data_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(snap, fname))
        self._set_head(new_head)
        self._prune()

    def _prune(self):
        versions = self._all_versions()
        while len(versions) > self.MAX_VERSIONS:
            shutil.rmtree(self._snap_dir(versions.pop(0)), ignore_errors=True)

    def undo(self):
        head = self._get_head()
        versions = self._all_versions()
        if head not in versions:
            raise ValueError("Historique introuvable")
        idx = versions.index(head)
        if idx == 0:
            raise ValueError("Déjà à la version la plus ancienne")
        prev = versions[idx - 1]
        snap = self._snap_dir(prev)
        for fname in ("tasks.csv", "node_positions.json"):
            src = os.path.join(snap, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(self.data_dir, fname))
        self._set_head(prev)

    def can_undo(self) -> bool:
        head = self._get_head()
        versions = self._all_versions()
        return head in versions and versions.index(head) > 0


_storage = LocalVersionedStorage()

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
COLOR_READY_QUICK = "#5B91A8"
COLOR_URGENT = "#A7B7C2"
COLOR_GOAL = "#C5BAD8"

# Couleurs de highlight (surlignage au clic : chaque nœud selon son statut réel)
COLOR_TODO_HL = "#7E8570"
COLOR_DONE_HL = "#B2B0AC"
COLOR_READY_HL = "#8FA1AB"
COLOR_URGENT_HL = "#8FA1AB"
COLOR_GOAL_HL = "#9B8FBF"

# Couleurs dédiées aux arêtes du surlignage (ancêtres vs descendants), pour garder la lecture du sens


def load_tasks_from_csv() -> Tuple[
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
    Dict[str, str],
    Dict[str, List[str]],
    Dict[str, List[str]],
    Dict[str, bool],
]:
    """Charge les tâches depuis le CSV et remplit les dictionnaires."""
    types_dict: Dict[str, str] = {}
    status_dict: Dict[str, str] = {}
    location_dict: Dict[str, str] = {}
    desc_dict: Dict[str, str] = {}
    pred_dict: Dict[str, List[str]] = {}
    follow_dict: Dict[str, List[str]] = {}
    quick_dict: Dict[str, bool] = {}

    text = _storage.read_text("tasks.csv")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
            i = row["id"].strip()
            if not i or not i.isdigit():
                continue
            types_dict[i] = row["type"].strip()
            _s = row["status"].strip()
            _canon = {"READY": "Ready", "TOBUY": "ToBuy", "READY-CRITIC": "Ready-Critic", "TOBUY-CRITIC": "ToBuy-Critic"}
            status_dict[i] = _canon.get(_s.upper(), _s.upper())
            location_dict[i] = row["location"].strip()
            desc_dict[i] = i + ": " + row["description"].strip()
            pred_str = row["predecessors"].strip().replace(" ", "")
            # On accepte l'ancien séparateur ',' et le nouveau '-'
            cleaned = pred_str.replace(",", "-")
            pred_dict[i] = [p for p in cleaned.split("-") if p] if cleaned else []
            quick_dict[i] = row.get("quick", "").strip() in ("1", "true", "True", "yes")

    # Suivants : pour chaque tâche, liste des tâches qui en dépendent
    for k in pred_dict:
        follow_dict[k] = []
    for k in pred_dict:
        for pred_id in pred_dict[k]:
            if pred_id in follow_dict:
                follow_dict[pred_id].append(k)

    return types_dict, status_dict, location_dict, desc_dict, pred_dict, follow_dict, quick_dict


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
            if status_dict[k] in ("TOPRIO", "Ready", "ToBuy", "Ready-Critic", "ToBuy-Critic"):
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
    quick_dict: Dict[str, bool] | None = None,
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

        is_quick = (quick_dict or {}).get(task_id, False)
        data = {
            "id": task_id,
            "label": ("⚡ " if is_quick else "") + desc_dict[task_id],
            "status": status_dict[task_id],
            "type": types_dict[task_id],
            "location": loc,
            "count_lockers": count_lockers.get(task_id, 0),
            "priority_path": task_id in priority_paths_tasks,
            "quick": is_quick,
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


def build_model_from_csv() -> Tuple[List[dict], dict]:
    """
    Point d'entrée de haut niveau pour étapes 1 & 2.
    Retourne :
      - la liste des éléments Cytoscape (nœuds + arêtes)
      - un dict 'meta' avec les structures de base (utile pour les futures callbacks).
    """
    types_dict, status_dict, location_dict, desc_dict, pred_dict, follow_dict, quick_dict = load_tasks_from_csv()
    raw_status_dict = dict(status_dict)  # sauvegarde avant mutation par compute_statuses
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
        quick_dict,
    )

    # Si un fichier de positions existe, on l'applique aux nœuds
    try:
        saved_positions = json.loads(_storage.read_text("node_positions.json"))
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
        "raw_status_dict": raw_status_dict,
        "location_dict": location_dict,
        "desc_dict": desc_dict,
        "pred_dict": pred_dict,
        "follow_dict": follow_dict,
        "count_lockers": count_lockers,
        "priority_paths_tasks": priority_paths_tasks,
        "quick_dict": quick_dict,
    }
    return elements, meta



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
        desc_dict = new_meta.get("desc_dict", {})
        quick_dict = new_meta.get("quick_dict", {})
        if node_id in desc_dict:
            data["label"] = ("⚡ " if quick_dict.get(node_id, False) else "") + desc_dict[node_id]
        data["quick"] = quick_dict.get(node_id, False)

    return out


def _recompute_meta(base_meta: dict, pred_dict: Dict[str, List[str]]) -> dict:
    """Recalcule le meta en mémoire à partir d'un pred_dict modifié, sans toucher au CSV."""
    follow_dict: Dict[str, List[str]] = {k: [] for k in pred_dict}
    for k, preds in pred_dict.items():
        for p in preds:
            if p in follow_dict:
                follow_dict[p].append(k)
    types_dict = base_meta.get("types_dict", {})
    # Toujours partir des statuts bruts (avant compute_statuses) pour éviter l'accumulation de TOPRIO
    raw_status = dict(base_meta.get("raw_status_dict") or base_meta.get("status_dict", {}))
    status_dict = dict(raw_status)  # copie car compute_statuses mute en place
    location_dict = base_meta.get("location_dict", {})
    desc_dict = base_meta.get("desc_dict", {})
    count_lockers, priority_paths_tasks = compute_statuses(types_dict, status_dict, location_dict, pred_dict, follow_dict)
    return {
        "types_dict": types_dict,
        "status_dict": status_dict,
        "raw_status_dict": raw_status,
        "location_dict": location_dict,
        "desc_dict": desc_dict,
        "pred_dict": pred_dict,
        "follow_dict": follow_dict,
        "count_lockers": count_lockers,
        "priority_paths_tasks": priority_paths_tasks,
        "quick_dict": base_meta.get("quick_dict", {}),
    }


def rebuild_elements_with_positions(new_meta: dict, old_elements: list) -> list:
    """Reconstruit les éléments depuis le meta (positions préservées depuis old_elements)."""
    new_els = build_cytoscape_elements(
        new_meta["types_dict"], new_meta["status_dict"], new_meta["location_dict"],
        new_meta["desc_dict"], new_meta["pred_dict"], new_meta["follow_dict"],
        new_meta["count_lockers"], new_meta["priority_paths_tasks"],
        new_meta.get("quick_dict", {}),
    )
    old_pos = {el["data"]["id"]: el["position"] for el in old_elements if "position" in el}
    for el in new_els:
        nid = el.get("data", {}).get("id")
        if nid and nid in old_pos:
            el["position"] = old_pos[nid]
    return new_els


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


def save_csv_from_meta(meta: dict) -> None:
    """Reécrit le CSV entier depuis le meta-store (pour synchroniser après changements en mémoire)."""
    types_dict = meta.get("types_dict", {})
    status_dict = meta.get("raw_status_dict") or meta.get("status_dict", {})  # statuts bruts sans TOPRIO/Ready
    location_dict = meta.get("location_dict", {})
    desc_dict = meta.get("desc_dict", {})
    pred_dict = meta.get("pred_dict", {})
    quick_dict = meta.get("quick_dict", {})
    all_ids = sorted(types_dict.keys(), key=lambda x: int(x) if x.isdigit() else 0)
    rows = []
    for i in all_ids:
        raw_desc = desc_dict.get(i, "")
        if raw_desc.startswith(i + ": "):
            raw_desc = raw_desc[len(i) + 2:]
        rows.append({
            "id": i,
            "type": types_dict.get(i, ""),
            "status": status_dict.get(i, ""),
            "location": location_dict.get(i, ""),
            "description": raw_desc,
            "predecessors": "-".join(pred_dict.get(i, [])),
            "quick": "1" if quick_dict.get(i, False) else "",
        })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["id", "type", "status", "location", "description", "predecessors", "quick"])
    writer.writeheader()
    writer.writerows(rows)
    _storage.write_text("tasks.csv", buf.getvalue())



def _would_create_cycle(
    pred_dict: Dict[str, List[str]], new_pred: str, successor_id: str
) -> bool:
    """True si ajouter new_pred comme prédécesseur de successor_id créerait un cycle."""
    ancestors, _ = _collect_ancestors(new_pred, pred_dict, max_depth=None)
    return successor_id in ancestors


# --- App Dash minimale : affichage statique du graphe ---

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
    # Cadres projet invisibles en mode exécution (séparateurs dessinés sur canvas overlay)
    {
        "selector": 'node[is_group = "True"].exec-hide-group',
        "style": {
            "background-opacity": 0,
            "border-width": 0,
            "label": "",
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
    {
        "selector": 'node[status *= "Ready"][?quick]',
        "style": {"background-color": COLOR_READY_QUICK},
    },
    {
        "selector": 'node[status *= "ToBuy"][?quick]',
        "style": {"background-color": COLOR_READY_QUICK},
    },
    {
        "selector": 'node[status = "TOPRIO"][?quick]',
        "style": {"background-color": COLOR_READY_QUICK},
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
    # Highlight chemin (taphold)
    {"selector": ".hl-path", "style": {"border-width": 5, "border-color": "#FF2222"}},
    {"selector": ".hl-edge", "style": {"line-color": "#FF2222", "target-arrow-color": "#FF2222", "width": 7}},
]


def build_execution_elements(elements_state: list) -> list:
    nodes = [
        el for el in elements_state
        if "source" not in el.get("data", {}) and el.get("data", {}).get("is_group") != "True"
    ]
    edges = [el for el in elements_state if "source" in el.get("data", {})]

    status_by_id = {n["data"]["id"]: n["data"].get("status", "") for n in nodes}

    preds_by_target: dict = {}
    for edge in edges:
        t = edge["data"]["target"]
        s = edge["data"]["source"]
        preds_by_target.setdefault(t, []).append(s)

    def is_unblocking(st: str) -> bool:
        return ("Ready" in st or "ToBuy" in st or "DONE" in st
                or st == "TOPRIO" or st == "PRIO")

    visible_ids: set = set()
    for nid, st in status_by_id.items():
        if "DONE" in st:
            continue
        if "Ready" in st or "ToBuy" in st or st == "TOPRIO" or st == "PRIO":
            visible_ids.add(nid)
        elif st == "TODO":
            preds = preds_by_target.get(nid, [])
            if preds and any(is_unblocking(status_by_id.get(p, "")) for p in preds):
                visible_ids.add(nid)

    result = []
    for el in elements_state:
        data = el.get("data", {})
        if data.get("is_group") == "True":
            continue
        if "source" in data:
            if data["source"] in visible_ids and data["target"] in visible_ids:
                result.append(el)
        elif data.get("id") in visible_ids:
            new_data = {k: v for k, v in data.items() if k != "parent"}
            new_el = dict(el)
            new_el["data"] = new_data
            result.append(new_el)
    return result


app = dash.Dash(__name__, title=f"Tasky {VERSION}")
server = app.server  # exposition pour gunicorn


def serve_layout():
    elements, meta = build_model_from_csv()
    has_preset = any(
        ("position" in el) and ("source" not in el.get("data", {})) for el in elements
    )
    initial_layout = {"name": "preset"} if has_preset else {"name": "cose-bilkent"}
    return html.Div(
        [
            html.Span(id="save-status", style={"font-size": "12px", "color": "#c00", "position": "fixed", "top": "8px", "left": "10px", "zIndex": "1100"}),
            html.Span(VERSION, style={"font-size": "11px", "color": "#bbb", "position": "fixed", "bottom": "6px", "right": "10px", "zIndex": "1100", "pointerEvents": "none"}),
            html.Button("▶ Exécution", id="view-toggle-btn", n_clicks=0, style={
                "position": "fixed", "top": "6px", "right": "10px",
                "zIndex": "1100", "fontSize": "13px",
                "background": "white", "border": "1px solid #ccc",
                "borderRadius": "6px", "padding": "4px 10px", "cursor": "pointer",
            }),
            html.Button("↩", id="undo-btn", n_clicks=0, title="Annuler",
                disabled=not _storage.can_undo(),
                style={
                    "position": "fixed", "top": "6px", "right": "145px",
                    "zIndex": "1100", "fontSize": "14px",
                    "background": "white", "border": "1px solid #ccc",
                    "borderRadius": "6px", "padding": "4px 10px", "cursor": "pointer",
                }),
            dcc.Store(id="meta-store", data=meta),
            dcc.Store(id="view-mode", data="planning"),
            dcc.Store(id="exec-view-applied", data=0),
            dcc.Store(id="exec-positions", data=None),
            dcc.Store(id="planning-elements-cache", data=None),
            dcc.Store(id="viewport-debug", data=None),
            dcc.Store(id="restore-viewport-trigger", data=None),
            dcc.Store(id="restore-viewport-done", data=0),
            dcc.Store(id="dragfree-trigger", data=0),
            cyto.Cytoscape(
                id="planning-graph",
                elements=elements,
                layout=initial_layout,
                style={"width": "100%", "height": "100vh", "border": "none"},
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
        style={"width": "100%", "height": "100vh", "padding": "0", "margin": "0", "overflow": "hidden", "backgroundColor": BG_COLOR},
    )


app.layout = serve_layout


clientside_callback(
    """
    function(n, cur) {
        var next = cur === 'planning' ? 'execution' : 'planning';
        window._viewMode = next;
        var btn = document.getElementById('view-toggle-btn');
        if (btn) btn.textContent = next === 'execution' ? '📋 Planification' : '▶ Exécution';
        return next;
    }
    """,
    Output("view-mode", "data"),
    Input("view-toggle-btn", "n_clicks"),
    State("view-mode", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    """
    function(viewMode) {
        if (!window.cy) return 0;
        if (viewMode === 'execution') {
            window._planningViewport = { zoom: window.cy.zoom(), pan: window.cy.pan() };
            var done = window.cy.nodes('[status *= "DONE"]');
            done.hide();
            done.connectedEdges().hide();
            function isUnblocking(p) {
                var st = p.data('status') || '';
                return st.indexOf('Ready') >= 0 || st.indexOf('ToBuy') >= 0 ||
                       st.indexOf('DONE') >= 0 || st === 'TOPRIO' || st === 'PRIO';
            }
            window.cy.nodes('[status = "TODO"],[status = "PRIO"]').forEach(function(node) {
                var preds = node.incomers('node');
                var loc = node.data('location');
                var blocked = preds.length > 0 && preds.some(function(p) { return !isUnblocking(p); });
                if (!blocked && node.data('status') === 'TODO') {
                    var hasSameProjUnblocking = preds.some(function(p) {
                        return isUnblocking(p) && p.data('location') === loc;
                    });
                    if (preds.length > 0 && !hasSameProjUnblocking) blocked = true;
                }
                if (blocked) { node.hide(); node.connectedEdges().hide(); }
            });
            window.cy.edges(':visible').forEach(function(edge) {
                if (edge.source().data('location') !== edge.target().data('location')) {
                    edge.hide();
                }
            });
            window.cy.nodes('[is_group = "True"]').addClass('exec-hide-group');
            window.cy.nodes('[is_group != "True"]').ungrabify();
            window.cy.fit(window.cy.elements(':visible'), 50);
            // Canvas overlay : lignes de séparation par projet
            var container = window.cy.container();
            var overlay = document.getElementById('cy-exec-overlay');
            if (!overlay) {
                overlay = document.createElement('canvas');
                overlay.id = 'cy-exec-overlay';
                overlay.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:10;';
                container.style.position = 'relative';
                container.appendChild(overlay);
            }
            function drawSeparators() {
                var rect = container.getBoundingClientRect();
                overlay.width = rect.width;
                overlay.height = rect.height;
                var ctx = overlay.getContext('2d');
                ctx.clearRect(0, 0, overlay.width, overlay.height);
                window.cy.nodes('[is_group = "True"]').forEach(function(node) {
                    if (node.children(':visible').length === 0) return;
                    var bb = node.renderedBoundingBox({ includeLabels: false });
                    var y = bb.y1;
                    ctx.beginPath();
                    ctx.moveTo(bb.x1, y);
                    ctx.lineTo(bb.x2, y);
                    ctx.strokeStyle = '#aaaaaa';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    var label = node.data('label') || '';
                    ctx.fillStyle = '#888888';
                    ctx.font = '12px sans-serif';
                    ctx.fillText(label, bb.x1 + 4, y - 4);
                });
            }
            window._execSepHandler = drawSeparators;
            window.cy.on('render', window._execSepHandler);
            drawSeparators();
        } else {
            // Retirer le canvas overlay
            if (window._execSepHandler) {
                window.cy.off('render', window._execSepHandler);
                window._execSepHandler = null;
            }
            var overlay = document.getElementById('cy-exec-overlay');
            if (overlay) {
                var ctx = overlay.getContext('2d');
                ctx.clearRect(0, 0, overlay.width, overlay.height);
            }
            window.cy.elements().show();
            window.cy.nodes('[is_group = "True"]').removeClass('exec-hide-group');
            window.cy.nodes('[is_group != "True"]').grabify();
        }
        return 0;
    }
    """,
    Output("exec-view-applied", "data"),
    Input("view-mode", "data"),
    prevent_initial_call=True,
)


@app.callback(
    Output("exec-positions", "data"),
    Input("view-mode", "data"),
    State("planning-graph", "elements"),
    State("meta-store", "data"),
    prevent_initial_call=True,
)
def compute_exec_positions(view_mode, elements_state, meta):
    if view_mode != "execution":
        return dash.no_update

    all_nodes = [
        el for el in (elements_state or [])
        if "source" not in el.get("data", {}) and el.get("data", {}).get("is_group") != "True"
    ]
    edges = [el for el in (elements_state or []) if "source" in el.get("data", {})]

    status_by_id = {n["data"]["id"]: n["data"].get("status", "") for n in all_nodes}
    node_data_by_id = {n["data"]["id"]: n["data"] for n in all_nodes}

    # Graphe complet (utilisé pour classer row0/row1)
    preds_all: dict = {}
    for edge in edges:
        s, t = edge["data"]["source"], edge["data"]["target"]
        preds_all.setdefault(t, []).append(s)

    def is_unblocking(st: str) -> bool:
        return "Ready" in st or "ToBuy" in st or "DONE" in st or st in ("TOPRIO", "PRIO")

    # Classer les nœuds visibles en ligne 0 (actionnables) ou ligne 1 (prochains)
    row0: set = set()
    row1: set = set()
    for nid, st in status_by_id.items():
        if "DONE" in st:
            continue
        if "Ready" in st or "ToBuy" in st or st == "TOPRIO":
            row0.add(nid)
        elif st == "PRIO":
            # PRIO visible seulement si tous les prédécesseurs sont DONE
            preds = preds_all.get(nid, [])
            if not preds or all("DONE" in status_by_id.get(p, "") for p in preds):
                row0.add(nid)
        elif st == "TODO":
            preds = preds_all.get(nid, [])
            loc = node_data_by_id[nid].get("location", "Sans projet")
            same_proj_unblocking = any(
                is_unblocking(status_by_id.get(p, "")) and
                node_data_by_id.get(p, {}).get("location", "") == loc
                for p in preds
            )
            if preds and same_proj_unblocking:
                row1.add(nid)

    # Graphe restreint aux nœuds visibles — utilisé pour tri barycentre et groupes
    visible = row0 | row1
    preds_by_target: dict = {}
    succs_by_source: dict = {}
    for edge in edges:
        s, t = edge["data"]["source"], edge["data"]["target"]
        if s in visible and t in visible:
            preds_by_target.setdefault(t, []).append(s)
            succs_by_source.setdefault(s, []).append(t)

    # Compter les tâches non-DONE par projet (sur tous les éléments, pas seulement visibles)
    remaining_by_project: dict = {}
    for n in all_nodes:
        loc = n["data"].get("location", "Sans projet")
        if "DONE" not in n["data"].get("status", ""):
            remaining_by_project[loc] = remaining_by_project.get(loc, 0) + 1

    # Grouper par projet
    by_project: dict = {}
    for nid in row0:
        loc = node_data_by_id[nid].get("location", "Sans projet")
        by_project.setdefault(loc, {0: [], 1: []})
        by_project[loc][0].append(nid)
    for nid in row1:
        loc = node_data_by_id[nid].get("location", "Sans projet")
        by_project.setdefault(loc, {0: [], 1: []})
        by_project[loc][1].append(nid)

    # Minimisation des croisements par heuristique barycentre (2 passes)
    def _barycenter(nid: str, neighbors: dict, index: dict) -> float:
        nb = [n for n in neighbors.get(nid, []) if n in index]
        return sum(index[n] for n in nb) / len(nb) if nb else float("inf")

    for loc in by_project:
        r0 = list(by_project[loc][0])
        r1 = list(by_project[loc][1])
        if not r0 or not r1:
            by_project[loc][0] = r0
            by_project[loc][1] = r1
            continue

        # Passe 1 : trier r1 par barycentre sur r0
        r0_idx = {nid: i for i, nid in enumerate(r0)}
        r1.sort(key=lambda nid: _barycenter(nid, preds_by_target, r0_idx))

        # Passe 2 : trier r0 par barycentre sur r1 (quick en tête, puis TOPRIO, puis le reste)
        r1_idx = {nid: i for i, nid in enumerate(r1)}
        quick     = [nid for nid in r0 if node_data_by_id[nid].get("quick")]
        toprio    = [nid for nid in r0 if not node_data_by_id[nid].get("quick") and status_by_id.get(nid) == "TOPRIO"]
        non_quick = [nid for nid in r0 if not node_data_by_id[nid].get("quick") and status_by_id.get(nid) != "TOPRIO"]
        quick.sort(key=lambda nid: _barycenter(nid, succs_by_source, r1_idx))
        toprio.sort(key=lambda nid: _barycenter(nid, succs_by_source, r1_idx))
        non_quick.sort(key=lambda nid: _barycenter(nid, succs_by_source, r1_idx))
        r0 = quick + toprio + non_quick

        # Passe 3 : retrier r1 avec le nouvel ordre r0
        r0_idx = {nid: i for i, nid in enumerate(r0)}
        r1.sort(key=lambda nid: _barycenter(nid, preds_by_target, r0_idx))

        by_project[loc][0] = r0
        by_project[loc][1] = r1

    # Trier les projets par nombre de tâches restantes (ascendant)
    sorted_projects = sorted(by_project.keys(), key=lambda loc: remaining_by_project.get(loc, 0))

    NODE_W   = 220
    GROUP_GAP = 80   # extra pixels between groups within a project
    ROW_H    = 140
    PROJ_GAP = 60

    positions: dict = {}
    y = 0.0
    for loc in sorted_projects:
        r0 = by_project[loc][0]
        r1 = by_project[loc][1]
        r0_set_proj = set(r0)
        r0_idx = {n: i for i, n in enumerate(r0)}
        r1_idx = {n: i for i, n in enumerate(r1)}

        # Union-find: group r0 nodes that share a r1 successor
        # so they can be placed together above that shared successor
        r0_rep: dict = {n: n for n in r0}

        def _find(x: str) -> str:
            while r0_rep[x] != x:
                r0_rep[x] = r0_rep[r0_rep[x]]
                x = r0_rep[x]
            return x

        for r1_nid in r1:
            preds = [p for p in preds_by_target.get(r1_nid, []) if p in r0_set_proj]
            if len(preds) > 1:
                root = _find(preds[0])
                for p in preds[1:]:
                    pr = _find(p)
                    if pr != root:
                        r0_rep[pr] = root

        comps: dict = {}
        for nid in r0:
            comps.setdefault(_find(nid), []).append(nid)
        groups = sorted(comps.values(), key=lambda g: r0_idx[g[0]])

        # STEP = espace uniforme entre slots (intra-groupe ET inter-groupes)
        # En intégrant GROUP_GAP dans le pas, tous les nœuds consécutifs sont
        # espacés identiquement, qu'ils soient dans le même groupe ou non.
        step = NODE_W + GROUP_GAP
        x = 0.0
        r0_px: dict = {}
        r1_px: dict = {}

        for group in groups:
            group_set = set(group)
            group_r1 = sorted(
                [t for t in r1 if any(p in group_set for p in preds_by_target.get(t, []))],
                key=lambda t: r1_idx[t],
            )
            n0 = len(group)
            n1 = len(group_r1)
            n_slots = max(n0, n1) if n1 else n0
            group_total = n_slots * step  # largeur du groupe (pas d'extra après)

            for i, nid in enumerate(group):
                r0_px[nid] = x + (i * (group_total - step) / (n0 - 1) if n0 > 1 else (group_total - step) / 2.0)
            for i, t in enumerate(group_r1):
                r1_px[t] = x + (i * (group_total - step) / (n1 - 1) if n1 > 1 else (group_total - step) / 2.0)

            x += group_total  # pas de +GROUP_GAP : déjà dans step

        for t in r1:
            if t not in r1_px:
                r1_px[t] = x
                x += step

        if r0:
            for nid in r0:
                positions[nid] = {"x": r0_px[nid], "y": y}
            y += ROW_H
        if r1:
            for t in r1:
                positions[t] = {"x": r1_px[t], "y": y}
            y += ROW_H
        y += PROJ_GAP

    return positions


clientside_callback(
    """
    function(execPositions) {
        if (!window.cy || !execPositions || Object.keys(execPositions).length === 0) return 0;
        window.cy.batch(function() {
            Object.keys(execPositions).forEach(function(id) {
                var n = window.cy.getElementById(id);
                if (n.length && !n.hidden()) n.position(execPositions[id]);
            });
        });
        window.cy.fit(window.cy.elements(':visible'), 50);
        return 0;
    }
    """,
    Output("exec-view-applied", "data", allow_duplicate=True),
    Input("exec-positions", "data"),
    prevent_initial_call=True,
)


@app.callback(
    Output("planning-graph", "elements", allow_duplicate=True),
    Output("planning-graph", "layout"),
    Input("view-mode", "data"),
    State("meta-store", "data"),
    prevent_initial_call=True,
)
def restore_planning_view(view_mode, meta):
    if view_mode != "planning":
        return dash.no_update, dash.no_update
    try:
        saved_positions = json.loads(_storage.read_text("node_positions.json"))
    except Exception:
        saved_positions = {}
    elements = rebuild_elements_with_positions(meta or {}, [])
    for el in elements:
        data = el.get("data", {})
        nid = data.get("id")
        if nid and "source" not in data and nid in saved_positions:
            el["position"] = saved_positions[nid]
    return elements, {"name": "preset", "fit": True, "padding": 50}


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
    function(_id) {
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
            var SNAP_GRID = 40;
            window._dragfreeCnt = 0;
            window.cy.on('dragfree', 'node', function(evt) {
                var node = evt.target;
                if (node.data('is_group') === 'True') return;
                var pos = node.position();
                node.position({
                    x: Math.round(pos.x / SNAP_GRID) * SNAP_GRID,
                    y: Math.round(pos.y / SNAP_GRID) * SNAP_GRID
                });
                // Déclenche la sauvegarde des positions côté serveur
                window._dragfreeCnt = (window._dragfreeCnt || 0) + 1;
                window.dash_clientside.set_props('dragfree-trigger', {data: window._dragfreeCnt});
            });

            // --- Mode création de lien ---
            window._linkMode = null; // {id, dir} dir="suivant"|"précédent"
            function enterLinkMode(nodeId, dir) {
                window._linkMode = {id: nodeId, dir: dir};
                window.cy.container().style.cursor = 'crosshair';
            }
            function exitLinkMode() {
                window._linkMode = null;
                window.cy.container().style.cursor = '';
            }

            // --- Highlight chemin (taphold) ---
            window._hlNode = null;
            window._hlDepth = 0;
            function applyHighlight(nodeId, depth) {
                window.cy.elements().removeClass('hl-path hl-edge');
                var focus = window.cy.getElementById(nodeId);
                var hlNodes = window.cy.collection().merge(focus);
                var hlEdges = window.cy.collection();
                var frontier = focus;
                for (var d = 0; d < depth; d++) {
                    var inc = frontier.incomers();
                    if (!inc.length) break;
                    hlNodes = hlNodes.merge(inc.nodes());
                    hlEdges = hlEdges.merge(inc.edges());
                    frontier = inc.nodes();
                }
                frontier = focus;
                for (var d = 0; d < depth; d++) {
                    var out = frontier.outgoers();
                    if (!out.length) break;
                    hlNodes = hlNodes.merge(out.nodes());
                    hlEdges = hlEdges.merge(out.edges());
                    frontier = out.nodes();
                }
                hlNodes.addClass('hl-path');
                hlEdges.addClass('hl-edge');
            }
            function exitHighlightMode() {
                window.cy.elements().removeClass('hl-path hl-edge');
                window._hlNode = null;
                window._hlDepth = 0;
            }
            window.cy.on('taphold', 'node', function(evt) {
                if (evt.target.data('is_group') === 'True') return;
                var nodeId = evt.target.id();
                if (window._hlNode === nodeId) {
                    window._hlDepth += 1;
                } else {
                    window._hlNode = nodeId;
                    window._hlDepth = 1;
                }
                applyHighlight(nodeId, window._hlDepth);
            });

            window._preClickSelected = false;
            window._tappedNodeId = null;
            window._tapToggleTimer = null;
            window.cy.on('tapstart', 'node', function(evt) {
                if (evt.target.data('is_group') === 'True') return;
                window.cy.selectionType('additive');
                window._preClickSelected = evt.target.selected();
                window._tappedNodeId = evt.target.id();
            });
            window.cy.on('tap', 'node', function(evt) {
                hideCtxMenu();
                if (evt.target.data('is_group') === 'True') return;
                if (window._linkMode) {
                    var clickedId = evt.target.id();
                    if (clickedId !== window._linkMode.id) {
                        var src = window._linkMode.dir === 'suivant' ? window._linkMode.id : clickedId;
                        var tgt = window._linkMode.dir === 'suivant' ? clickedId : window._linkMode.id;
                        dispatch({action: "create_edge", source: src, target: tgt});
                    }
                    exitLinkMode();
                    return;
                }
                if (window._preClickSelected && evt.target.id() === window._tappedNodeId) {
                    // Delayed toggle : annulé si dbltap arrive avant
                    if (window._tapToggleTimer) clearTimeout(window._tapToggleTimer);
                    var _el = evt.target;
                    window._tapToggleTimer = setTimeout(function() {
                        window._tapToggleTimer = null;
                        _el.unselect();
                    }, 300);
                }
            });

            // --- Toggle-select arêtes ---
            window.cy.on('tap', 'edge', function(evt) {
                hideCtxMenu();
                if (window._linkSource) { exitLinkMode(); return; }
                var el = evt.target;
                if (el.hasClass('edge-selected')) deselectEdge(el);
                else selectEdge(el);
            });

            // Clic sur fond : effacer sélection + menu (+ annule mode lien)
            window.cy.on('tap', function(evt) {
                if (evt.target === window.cy) { clearEdgeSelection(); window.cy.$(':selected').unselect(); hideCtxMenu(); exitLinkMode(); exitHighlightMode(); }
            });

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') { hideCtxMenu(); exitLinkMode(); window.cy.$(':selected').unselect(); clearEdgeSelection(); exitHighlightMode(); }
            });


            // --- Utilitaires menu multi-niveaux ---
            function shortLabel(lbl) {
                return (lbl || '').length > 28 ? (lbl || '').substring(0, 26) + '…' : (lbl || '');
            }
            function dispatch(action_obj) {
                window.cy.$(':selected').unselect();
                clearEdgeSelection();
                window._ctxAction = action_obj;
                document.getElementById('ctx-confirm-btn').click();
                hideCtxMenu();
            }
            function menuRow(label, onclick, opts) {
                var el = document.createElement('div');
                el.textContent = label;
                var css = 'padding:5px 14px;cursor:pointer;white-space:nowrap;font-size:13px;';
                if (opts && opts.separator) css += 'border-top:1px solid #e0e0e0;';
                if (opts && opts.bold) css += 'font-weight:600;';
                el.style.cssText = css;
                el.onmouseenter = function(){ el.style.background = '#f0f0f0'; };
                el.onmouseleave = function(){ el.style.background = ''; };
                el.onclick = onclick;
                return el;
            }
            function renderMenu(rows) {
                ctxMenu.innerHTML = '';
                rows.forEach(function(r) { ctxMenu.appendChild(r); });
            }
            function showMenu(rows, x, y) {
                renderMenu(rows);
                ctxMenu.style.left = x + 'px';
                ctxMenu.style.top  = y + 'px';
                ctxMenu.style.display = 'block';
                setTimeout(function() {
                    var r = ctxMenu.getBoundingClientRect();
                    if (r.right  > window.innerWidth)  ctxMenu.style.left = (x - r.width)  + 'px';
                    if (r.bottom > window.innerHeight)  ctxMenu.style.top  = (y - r.height) + 'px';
                }, 0);
            }

            function buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode) {
                var rows = [];

                if (isOnNode && nodeIds.length > 0) {
                    var curStatus = target.data('status') || '';
                    var isTodo = curStatus === 'TODO' || curStatus.indexOf('Ready') >= 0 || curStatus.indexOf('ToBuy') >= 0;
                    var isPrio = curStatus === 'PRIO' || curStatus === 'TOPRIO';
                    var isDone = curStatus.indexOf('DONE') >= 0;
                    rows.push(menuRow((isTodo ? "✓ " : "   ") + "TODO",    function(){ dispatch({action:"set_status", node_ids:nodeIds, status:"TODO"}); }));
                    rows.push(menuRow((isPrio ? "✓ " : "   ") + "PRIO ⭐", function(){ dispatch({action:"set_status", node_ids:nodeIds, status:"PRIO"}); }));
                    rows.push(menuRow((isDone ? "✓ " : "   ") + "DONE",    function(){ dispatch({action:"set_status", node_ids:nodeIds, status:"DONE"}); }));
                    var isQuick = target.data('quick');
                    var isBuy   = target.data('type') === 'A';
                    rows.push(menuRow((isQuick ? "✓ " : "   ") + "⚡ Rapide", function(){ dispatch({action:"toggle_quick", node_ids:nodeIds}); }));
                    rows.push(menuRow((isBuy   ? "✓ " : "   ") + "🛒 Achat",  function(){ dispatch({action:"toggle_buy",   node_ids:nodeIds}); }));
                    if (window._viewMode !== 'execution') {
                        var sep1 = document.createElement('div'); sep1.style.cssText = 'border-top:1px solid #e0e0e0;margin:4px 0;'; rows.push(sep1);
                    }
                }

                var showNewNodeForm = function(actionObj) {
                    renderMenu([menuRow("← retour", function(){ renderMenu(buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode)); })]);
                    var inp = document.createElement('input');
                    inp.type = 'text'; inp.placeholder = 'Nom de la tâche';
                    inp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                    ctxMenu.appendChild(inp);
                    var btn = document.createElement('button');
                    btn.textContent = 'Valider';
                    btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                    btn.onclick = function() {
                        var v = inp.value.trim();
                        if (v) dispatch(Object.assign({name: v}, actionObj));
                    };
                    ctxMenu.appendChild(btn);
                    inp.focus();
                    inp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                };

                if (window._viewMode !== 'execution') {
                    if (isOnNode && nodeIds.length === 1 && edgeIds.length === 0) {
                        var lnkId = target.id();
                        var tProj = target.data('location') || '';
                        var tPos  = target.position();
                        rows.push(menuRow("→ Lien vers",      function(id){ return function(){ hideCtxMenu(); enterLinkMode(id, 'suivant'); };   }(lnkId)));
                        rows.push(menuRow("✚ Créer suivant",  function(tp, px, py){ return function(){ showNewNodeForm({action:"create_node", project:tp, position:{x:px+160, y:py}, successor_of:target.id()}); }; }(tProj, tPos.x, tPos.y)));
                        rows.push(menuRow("← Lien depuis",    function(id){ return function(){ hideCtxMenu(); enterLinkMode(id, 'précédent'); }; }(lnkId)));
                        rows.push(menuRow("✚ Créer précédent",function(tp, px, py){ return function(){ showNewNodeForm({action:"create_node", project:tp, position:{x:px-160, y:py}, predecessor_of:target.id()}); }; }(tProj, tPos.x, tPos.y)));
                        var sep2 = document.createElement('div'); sep2.style.cssText = 'border-top:1px solid #e0e0e0;margin:4px 0;'; rows.push(sep2);
                    }

                    if (isOnNode) {
                        var otherSel = selNodes.not('#' + target.id());
                        if (otherSel.length === 1) {
                            var other = otherSel[0];
                            var otherLbl = shortLabel(other.data('label') || other.id());
                            rows.push(menuRow("↩ suit " + otherLbl, function(){ dispatch({action:"create_edge", source:other.id(), target:target.id()}); }));
                            rows.push(menuRow("↪ précède " + otherLbl, function(){ dispatch({action:"create_edge", source:target.id(), target:other.id()}); }));
                        }
                    }

                    if (isOnNode && nodeIds.length === 1) {
                        rows.push(menuRow("✏ Renommer", function() {
                            var currentDesc = (target.data('label') || '').replace(/^[0-9]+: */, '');
                            renderMenu([
                                menuRow("← retour", function(){ renderMenu(buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode)); }),
                            ]);
                            var inp = document.createElement('input');
                            inp.type = 'text'; inp.value = currentDesc;
                            inp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                            ctxMenu.appendChild(inp);
                            var btn = document.createElement('button');
                            btn.textContent = 'Valider';
                            btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                            btn.onclick = function() {
                                var v = inp.value.trim();
                                if (v) dispatch({action:"rename_node", node_id:nodeIds[0], new_name:v});
                            };
                            ctxMenu.appendChild(btn);
                            inp.focus(); inp.select();
                            inp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                        }));
                    }

                    if (isOnNode && nodeIds.length > 0) {
                        rows.push(menuRow("📁 Projet ▶", function() {
                            var projects = window.cy.nodes('[is_group = "True"]')
                                .map(function(n){ return n.data('label'); })
                                .filter(function(l){ return !!l; })
                                .sort();
                            var subRows = [menuRow("← retour", function(){ renderMenu(buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode)); })];
                            projects.forEach(function(proj) {
                                subRows.push(menuRow("📁 " + proj, function(p){ return function(){ dispatch({action:"move_node", node_ids:nodeIds, project:p}); }; }(proj)));
                            });
                            subRows.push(menuRow("✚ Nouveau projet…", function() {
                                renderMenu([menuRow("← retour", function(){ renderMenu(buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode)); })]);
                                var inp = document.createElement('input');
                                inp.type = 'text'; inp.placeholder = 'Nom du projet';
                                inp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                                ctxMenu.appendChild(inp);
                                var btn = document.createElement('button');
                                btn.textContent = 'Valider';
                                btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                                btn.onclick = function() {
                                    var v = inp.value.trim();
                                    if (v) dispatch({action:"move_node", node_ids:nodeIds, project:v});
                                };
                                ctxMenu.appendChild(btn);
                                inp.focus();
                                inp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                            }, {separator: true}));
                            renderMenu(subRows);
                        }));
                    }

                    if (nodeIds.length > 0 || edgeIds.length > 0) {
                        var parts = [];
                        if (nodeIds.length > 1) parts.push(nodeIds.length + " nœuds");
                        if (edgeIds.length === 1) parts.push("1 lien");
                        else if (edgeIds.length > 1) parts.push(edgeIds.length + " liens");
                        var deleteLabel = parts.length > 0 ? "🗑 Supprimer " + parts.join(" et ") : "🗑 Supprimer";
                        rows.push(menuRow(deleteLabel,
                            function(){ dispatch({action:"delete_selection", node_ids:nodeIds, edge_ids:edgeIds}); }));
                    }
                }



                return rows;
            }

            // --- Menu contextuel (clic droit / double-clic) ---
            function handleContextMenu(evt) {
                var target = evt.target;
                var isBg = (target === window.cy);

                if (!isBg) {
                    if (target.isEdge()) { if (!target.hasClass('edge-selected')) selectEdge(target); }
                    else if (target.isNode() && target.data('is_group') !== 'True') { if (!target.selected()) target.select(); }
                }

                var oe = evt.originalEvent;
                var x, y;
                if (oe && oe.clientX !== undefined) {
                    x = oe.clientX; y = oe.clientY;
                } else if (oe && oe.changedTouches && oe.changedTouches.length) {
                    x = oe.changedTouches[0].clientX; y = oe.changedTouches[0].clientY;
                } else {
                    var rp = evt.renderedPosition;
                    var rect0 = window.cy.container().getBoundingClientRect();
                    x = rect0.left + rp.x; y = rect0.top + rp.y;
                }

                var selEdges = window.cy.edges('.edge-selected');
                var selNodes = window.cy.$(":selected").filter("node").not('[is_group = "True"]');
                var edgeIds = selEdges.map(function(e){ return e.id(); });
                var nodeIds = selNodes.map(function(n){ return n.id(); });
                var isOnNode = !isBg && target.isNode() && target.data('is_group') !== 'True';

                // --- Menu fond (clic droit dans le vide) ---
                if (isBg) {
                    var container = window.cy.container();
                    var contRect = container.getBoundingClientRect();
                    var zoom = window.cy.zoom();
                    var pan = window.cy.pan();
                    var modelX = (evt.originalEvent.clientX - contRect.left - pan.x) / zoom;
                    var modelY = (evt.originalEvent.clientY - contRect.top - pan.y) / zoom;

                    var clickedGroup = null;
                    window.cy.nodes('[is_group = "True"]').each(function(n) {
                        var bb = n.boundingBox();
                        if (modelX >= bb.x1 && modelX <= bb.x2 && modelY >= bb.y1 && modelY <= bb.y2) {
                            clickedGroup = n;
                        }
                    });

                    var bgRows = [];

                    var showCreateForm = function(projName, backFn) {
                        renderMenu([menuRow("← retour", backFn)]);
                        var inp = document.createElement('input');
                        inp.type = 'text'; inp.placeholder = 'Nom de la tâche';
                        inp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                        ctxMenu.appendChild(inp);
                        var btn = document.createElement('button');
                        btn.textContent = 'Valider';
                        btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                        btn.onclick = function() {
                            var v = inp.value.trim();
                            if (v) dispatch({action:"create_node", name:v, project:projName, position:{x:modelX, y:modelY}});
                        };
                        ctxMenu.appendChild(btn);
                        inp.focus();
                        inp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                    };

                    if (clickedGroup) {
                        var projName = clickedGroup.data('label') || '';
                        var groupId = clickedGroup.id();
                        var groupChildren = window.cy.nodes().filter(function(n) {
                            return n.data('parent') === groupId && n.data('is_group') !== 'True';
                        });
                        bgRows.push(menuRow("✚ Nouvelle tâche dans " + projName, function(pn) {
                            return function() { showCreateForm(pn, function() { showMenu(bgRows, x, y); }); };
                        }(projName)));
                        bgRows.push(menuRow("✏ Renommer " + projName, function(pn) {
                            return function() {
                                renderMenu([menuRow("← retour", function(){ showMenu(bgRows, x, y); })]);
                                var inp = document.createElement('input');
                                inp.type = 'text'; inp.value = pn;
                                inp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                                ctxMenu.appendChild(inp);
                                var btn = document.createElement('button');
                                btn.textContent = 'Valider';
                                btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                                btn.onclick = function() {
                                    var v = inp.value.trim();
                                    if (v && v !== pn) dispatch({action:"rename_project", old_name:pn, new_name:v});
                                    else hideCtxMenu();
                                };
                                ctxMenu.appendChild(btn);
                                inp.focus(); inp.select();
                                inp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                            };
                        }(projName)));
                        bgRows.push(menuRow("☑ Sélectionner " + projName, function() {
                            hideCtxMenu();
                            setTimeout(function() {
                                window.cy.$(':selected').unselect();
                                clearEdgeSelection();
                                groupChildren.select();
                            }, 50);
                        }, {separator: true}));
                    } else {
                        bgRows.push(menuRow("✚ Nouvelle tâche…", function() {
                            var projects = window.cy.nodes('[is_group = "True"]')
                                .map(function(n){ return n.data('label') || ''; })
                                .filter(function(l){ return !!l; })
                                .sort();
                            var subRows = [menuRow("← retour", function(){ showMenu(bgRows, x, y); })];
                            projects.forEach(function(proj) {
                                subRows.push(menuRow("📁 " + proj, function(pn){ return function() {
                                    showCreateForm(pn, function(){ renderMenu(subRows); });
                                }; }(proj)));
                            });
                            subRows.push(menuRow("✚ Nouveau projet…", function() {
                                renderMenu([menuRow("← retour", function(){ renderMenu(subRows); })]);
                                var projInp = document.createElement('input');
                                projInp.type = 'text'; projInp.placeholder = 'Nom du projet';
                                projInp.style.cssText = 'margin:6px 10px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                                ctxMenu.appendChild(projInp);
                                var taskInp = document.createElement('input');
                                taskInp.type = 'text'; taskInp.placeholder = 'Nom de la tâche';
                                taskInp.style.cssText = 'margin:2px 10px 6px;padding:5px;width:calc(100% - 28px);box-sizing:border-box;';
                                ctxMenu.appendChild(taskInp);
                                var btn = document.createElement('button');
                                btn.textContent = 'Valider';
                                btn.style.cssText = 'margin:0 10px 8px;padding:5px 12px;cursor:pointer;';
                                btn.onclick = function() {
                                    var pv = projInp.value.trim(), tv = taskInp.value.trim();
                                    if (pv && tv) dispatch({action:"create_node", name:tv, project:pv, position:{x:modelX, y:modelY}});
                                };
                                ctxMenu.appendChild(btn);
                                projInp.focus();
                                projInp.onkeydown = function(e){ if (e.key==='Enter') taskInp.focus(); };
                                taskInp.onkeydown = function(e){ if (e.key==='Enter') btn.onclick(); };
                            }, {separator: true}));
                            renderMenu(subRows);
                        }));
                    }

                    if (bgRows.length > 0) showMenu(bgRows, x, y);
                    return;
                }

                var mainRows = buildMainMenu(target, selNodes, nodeIds, edgeIds, isOnNode);
                if (mainRows.length === 0) { hideCtxMenu(); return; }
                showMenu(mainRows, x, y);
            }

            window.cy.on('cxttap', function(evt) {
                evt.originalEvent.preventDefault();
                handleContextMenu(evt);
            });
            window.cy.on('dbltap', function(evt) {
                var target = evt.target;
                if (target === window.cy) {
                    // Fond : zoom intelligent
                    var ZOOM_IN_LEVEL = 0.5;
                    var ZOOM_NEAR_THRESHOLD = 0.35;
                    var currentZoom = window.cy.zoom();
                    var pos = evt.position;
                    var clickedGroup = null;
                    window.cy.nodes('[is_group = "True"]').each(function(n) {
                        var bb = n.boundingBox();
                        if (pos.x >= bb.x1 && pos.x <= bb.x2 && pos.y >= bb.y1 && pos.y <= bb.y2) clickedGroup = n;
                    });
                    if (clickedGroup) {
                        if (currentZoom >= ZOOM_NEAR_THRESHOLD) window.cy.animate({ fit: { eles: clickedGroup, padding: 40 } }, { duration: 400 });
                        else window.cy.animate({ zoom: { level: ZOOM_IN_LEVEL, position: pos } }, { duration: 400 });
                    } else {
                        window.cy.animate({ fit: { eles: window.cy.elements(), padding: 50 } }, { duration: 400 });
                    }
                } else {
                    // Nœud ou arête : annule le toggle tap en attente, puis menu contextuel
                    if (window._tapToggleTimer) { clearTimeout(window._tapToggleTimer); window._tapToggleTimer = null; }
                    handleContextMenu(evt);
                }
            });

        }

        // Enregistre les handlers dès que cy est prêt (avec retries si pas encore initialisé)
        registerHandlers();
        if (!window._cyHandlersRegistered) {
            setTimeout(registerHandlers, 300);
            setTimeout(registerHandlers, 800);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("restore-viewport-done", "data", allow_duplicate=True),
    Input("planning-graph", "id"),
    prevent_initial_call="initial_duplicate",
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


@app.callback(
    Output("save-status", "children"),
    Input("dragfree-trigger", "data"),
    State("planning-graph", "elements"),
    State("view-mode", "data"),
    prevent_initial_call=True,
)
def save_positions_on_dragfree(trigger, elements_state, view_mode):
    """Sauvegarde les positions dans tasky-data à chaque déplacement de nœud."""
    if not trigger or view_mode == "execution":
        return dash.no_update
    positions = _extract_positions(elements_state or [])
    if not positions:
        return dash.no_update
    try:
        _storage.write_text("node_positions.json", json.dumps(positions, indent=2))
    except Exception as exc:
        return f"Erreur: {exc}"
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
    m = meta_data or {}

    def _finalize(new_els, new_m):
        try:
            save_csv_from_meta(new_m)
        except Exception:
            pass
        return new_els, new_m, (viewport_debug or {}).get("extent")

    if action == "delete_selection":
        edge_ids = action_data.get("edge_ids", [])
        node_ids_to_delete = set(action_data.get("node_ids", []))
        if not edge_ids and not node_ids_to_delete:
            return dash.no_update, dash.no_update, dash.no_update

        # Supprimer les arêtes explicitement sélectionnées + toutes celles liées aux nœuds supprimés
        edge_ids_set = set(edge_ids)
        new_elements = [
            el for el in (elements_state or [])
            if el.get("data", {}).get("id") not in node_ids_to_delete
            and el.get("data", {}).get("id") not in edge_ids_set
            and el.get("data", {}).get("source") not in node_ids_to_delete
            and el.get("data", {}).get("target") not in node_ids_to_delete
        ]
        # Mettre à jour les dicts meta en retirant les nœuds supprimés
        raw_src = m.get("raw_status_dict") or m.get("status_dict", {})
        base_meta = {
            "types_dict":      {k: v for k, v in m.get("types_dict", {}).items()    if k not in node_ids_to_delete},
            "status_dict":     {k: v for k, v in m.get("status_dict", {}).items()   if k not in node_ids_to_delete},
            "raw_status_dict": {k: v for k, v in raw_src.items()                    if k not in node_ids_to_delete},
            "location_dict":   {k: v for k, v in m.get("location_dict", {}).items() if k not in node_ids_to_delete},
            "desc_dict":       {k: v for k, v in m.get("desc_dict", {}).items()     if k not in node_ids_to_delete},
        }
        pred_dict = {
            k: [p for p in v if p not in node_ids_to_delete]
            for k, v in m.get("pred_dict", {}).items()
            if k not in node_ids_to_delete
        }
        # Retirer aussi les liens sélectionnés du pred_dict
        for edge_id in edge_ids:
            if "->" in edge_id:
                src, tgt = edge_id.split("->", 1)
                if tgt in pred_dict and src in pred_dict[tgt]:
                    pred_dict[tgt] = [p for p in pred_dict[tgt] if p != src]
        new_meta = _recompute_meta(base_meta, pred_dict)
        new_elements = patch_elements_after_dependency_change(new_elements, None, None, new_meta)
        return _finalize(new_elements, new_meta)

    if action == "create_edge":
        source = action_data.get("source")
        target = action_data.get("target")
        if not source or not target:
            return dash.no_update, dash.no_update, dash.no_update
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        if source in pred_dict.get(target, []):
            return dash.no_update, dash.no_update, dash.no_update
        if _would_create_cycle(pred_dict, source, target):
            return dash.no_update, dash.no_update, dash.no_update
        pred_dict.setdefault(target, []).append(source)
        new_meta = _recompute_meta(m, pred_dict)
        new_elements = patch_elements_after_dependency_change(list(elements_state or []), (source, target), None, new_meta)
        return _finalize(new_elements, new_meta)

    if action == "set_status":
        node_ids = action_data.get("node_ids", [])
        new_status = action_data.get("status")
        if not node_ids or not new_status:
            return dash.no_update, dash.no_update, dash.no_update
        raw_status = dict(m.get("raw_status_dict") or m.get("status_dict", {}))
        for nid in node_ids:
            if nid in raw_status:
                raw_status[nid] = new_status
        base = dict(m)
        base["raw_status_dict"] = raw_status
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = patch_elements_after_dependency_change(list(elements_state or []), None, None, new_meta)
        return _finalize(new_elements, new_meta)

    if action == "rename_node":
        node_id = action_data.get("node_id")
        new_name = action_data.get("new_name", "").strip()
        if not node_id or not new_name:
            return dash.no_update, dash.no_update, dash.no_update
        desc_dict = dict(m.get("desc_dict", {}))
        desc_dict[node_id] = f"{node_id}: {new_name}"
        base = dict(m)
        base["desc_dict"] = desc_dict
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = patch_elements_after_dependency_change(list(elements_state or []), None, None, new_meta)
        return _finalize(new_elements, new_meta)

    if action == "move_node":
        node_ids = action_data.get("node_ids", [])
        project = action_data.get("project", "").strip()
        if not node_ids or not project:
            return dash.no_update, dash.no_update, dash.no_update
        location_dict = dict(m.get("location_dict", {}))
        for nid in node_ids:
            if nid in location_dict:
                location_dict[nid] = project
        base = dict(m)
        base["location_dict"] = location_dict
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = rebuild_elements_with_positions(new_meta, list(elements_state or []))
        return _finalize(new_elements, new_meta)

    if action == "rename_project":
        old_name = action_data.get("old_name", "").strip()
        new_name = action_data.get("new_name", "").strip()
        if not old_name or not new_name or old_name == new_name:
            return dash.no_update, dash.no_update, dash.no_update
        location_dict = dict(m.get("location_dict", {}))
        for nid, loc in location_dict.items():
            if loc == old_name:
                location_dict[nid] = new_name
        base = dict(m)
        base["location_dict"] = location_dict
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        # Patcher en place : changer uniquement le label du groupe et la location des enfants.
        # On ne touche PAS à l'ID du groupe ni au champ parent des enfants pour éviter
        # que cytoscape supprime les enfants lors du diff de compound nodes.
        old_group_id = f"group::{old_name}"
        new_elements = copy.deepcopy(list(elements_state or []))
        for el in new_elements:
            data = el.get("data", {})
            if data.get("id") == old_group_id:
                data["label"] = new_name
            elif data.get("parent") == old_group_id:
                data["location"] = new_name
        try:
            save_csv_from_meta(new_meta)
        except Exception:
            pass
        return new_elements, new_meta, None

    if action == "create_node":
        name = action_data.get("name", "").strip()
        project = action_data.get("project", "").strip()
        if not name or not project:
            return dash.no_update, dash.no_update, dash.no_update
        existing_ids = [int(k) for k in m.get("types_dict", {}).keys() if k.isdigit()]
        new_id = str(max(existing_ids) + 1) if existing_ids else "1"
        types_dict = dict(m.get("types_dict", {}))
        raw_status = dict(m.get("raw_status_dict") or m.get("status_dict", {}))
        location_dict = dict(m.get("location_dict", {}))
        desc_dict = dict(m.get("desc_dict", {}))
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        types_dict[new_id] = "F"
        raw_status[new_id] = "TODO"
        location_dict[new_id] = project
        desc_dict[new_id] = f"{new_id}: {name}"
        pred_dict[new_id] = []
        successor_of = action_data.get("successor_of")   # new_id vient APRÈS successor_of
        if successor_of and successor_of in pred_dict:
            pred_dict[new_id].append(successor_of)
        predecessor_of = action_data.get("predecessor_of")  # new_id vient AVANT predecessor_of
        if predecessor_of and predecessor_of in pred_dict:
            pred_dict[predecessor_of] = pred_dict.get(predecessor_of, []) + [new_id]
        base = dict(m)
        base["types_dict"] = types_dict
        base["raw_status_dict"] = raw_status
        base["location_dict"] = location_dict
        base["desc_dict"] = desc_dict
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = rebuild_elements_with_positions(new_meta, list(elements_state or []))
        pos = action_data.get("position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            for el in new_elements:
                if el.get("data", {}).get("id") == new_id:
                    el["position"] = {"x": float(pos["x"]), "y": float(pos["y"])}
                    break
        return _finalize(new_elements, new_meta)

    if action == "toggle_quick":
        node_ids = action_data.get("node_ids", [])
        if not node_ids:
            return dash.no_update, dash.no_update, dash.no_update
        quick_dict = dict(m.get("quick_dict", {}))
        for nid in node_ids:
            quick_dict[nid] = not quick_dict.get(nid, False)
        base = dict(m)
        base["quick_dict"] = quick_dict
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = patch_elements_after_dependency_change(list(elements_state or []), None, None, new_meta)
        return _finalize(new_elements, new_meta)

    if action == "toggle_buy":
        node_ids = action_data.get("node_ids", [])
        if not node_ids:
            return dash.no_update, dash.no_update, dash.no_update
        types_dict = dict(m.get("types_dict", {}))
        for nid in node_ids:
            types_dict[nid] = "F" if types_dict.get(nid) == "A" else "A"
        base = dict(m)
        base["types_dict"] = types_dict
        pred_dict = {k: list(v) for k, v in m.get("pred_dict", {}).items()}
        new_meta = _recompute_meta(base, pred_dict)
        new_elements = patch_elements_after_dependency_change(list(elements_state or []), None, None, new_meta)
        return _finalize(new_elements, new_meta)

    return dash.no_update, dash.no_update, dash.no_update


@app.callback(
    [
        Output("planning-graph", "elements", allow_duplicate=True),
        Output("meta-store", "data", allow_duplicate=True),
        Output("restore-viewport-trigger", "data", allow_duplicate=True),
        Output("undo-btn", "disabled"),
    ],
    Input("undo-btn", "n_clicks"),
    State("viewport-debug", "data"),
    prevent_initial_call=True,
)
def undo_action(n_clicks, viewport_debug):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    try:
        _storage.undo()
    except ValueError:
        return dash.no_update, dash.no_update, dash.no_update, True
    elements, meta = build_model_from_csv()
    return elements, meta, (viewport_debug or {}).get("extent"), not _storage.can_undo()


if __name__ == "__main__":
    # Lancement du serveur Dash (Dash >= 3 : run_server est obsolète)
    app.run(debug=True)
