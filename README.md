# Tasky — déploiement multi-utilisateur (VPS)

Ce document décrit comment Tasky est déployé sur le VPS (`tasky.dynetah.com`) pour
plusieurs personnes (fabien, yoan, davy...), avec un login self-service. Pour la doc
du code applicatif lui-même, voir [app/CLAUDE.md](app/CLAUDE.md).

## Arborescence

```
/home/fabien/tasky/
├── .git/                   ← racine du repo (github.com/fabien-arnaud/Tasky)
├── app/                    ← code de l'appli Dash (tasky.py), partagé par tout le monde
│   └── seed/               ← fichiers exemples utilisés pour initialiser un nouveau compte
├── auth/                   ← micro-service de login self-service (voir plus bas)
├── data/<prenom>/          ← données de chaque personne, isolées, jamais versionnées
└── backup/                 ← repo git séparé (tasky-backup), backup horaire des données de fabien
```

## Comment ça route : un seul domaine, plusieurs comptes

1. Tout le monde va sur `https://tasky.dynetah.com`.
2. nginx (`/etc/nginx/sites-available/tasky`) fait un `auth_request` vers le service
   `tasky-auth` (`auth/app.py`) sur chaque requête à `/`.
3. Si la session est valide, `tasky-auth` renvoie un header `X-User: <prenom>`.
4. Un `map` nginx (`/etc/nginx/tasky_users_map.conf`, chargé depuis
   `/etc/nginx/conf.d/tasky-map.conf`) traduit ce prénom en socket unix du bon
   processus gunicorn (`fabien` → `/run/tasky/tasky.sock`, `yoan` → `/run/tasky-yoan/...`, etc.)
5. Chaque personne a son propre processus gunicorn (`tasky.service`, `tasky-yoan.service`,
   `tasky-davy.service`...) avec son propre `DATA_DIR=/home/fabien/tasky/data/<prenom>`,
   donc ses propres `tasks.csv` / `node_positions.json` / historique.

Résultat : même code (`app/tasky.py`) partagé, données totalement isolées.

## Le login self-service (`auth/`)

`auth/app.py` est une petite appli Flask (service systemd `tasky-auth`, venv dédié) :

- `GET/POST /login` : la personne tape son prénom.
  - Prénom inconnu → message d'erreur, contacter fabien.
  - Prénom connu, pas encore de mot de passe → formulaire de création.
  - Prénom connu, mot de passe déjà créé → formulaire de connexion classique.
- `GET /verify` : endpoint interne appelé par nginx (`auth_request`) pour valider la session.
- Comptes stockés dans `auth/users.json` (jamais commité, jamais lisible sur GitHub) :
  ```json
  {"prenom": {"password_hash": "...", "session_version": 0}}
  ```
- La session est un cookie signé (clé dans `auth/secret_key`, jamais commitée). Chaque
  session porte le `session_version` de l'utilisateur au moment de la connexion ; si ce
  nombre ne correspond plus à celui de `users.json`, la session est refusée (401) — c'est
  le mécanisme de révocation (voir plus bas).

## Actions courantes

### Ajouter un nouvel ami
```bash
/home/fabien/tasky/auth/add_user.sh <prenom>
```
Crée son compte (`users.json`), son dossier de données (seedé depuis `app/seed/`), son
service systemd dédié, met à jour le routage nginx, recharge tout. Quasi immédiat.

### Réinitialiser le mot de passe de quelqu'un
```bash
/home/fabien/tasky/auth/reset_password.sh
```
Script interactif : liste les prénoms, tu choisis, il remet `password_hash` à `null`
**et** incrémente `session_version` — ce qui déconnecte immédiatement toute session déjà
ouverte pour cette personne (même sur un autre appareil), pas seulement le prochain login.

### Déployer une mise à jour du code
```bash
/home/fabien/tasky/app/deploy.sh   # depuis un poste avec le repo cloné
# ou, directement sur le VPS :
/home/fabien/tasky/app/update.sh
```
Redémarre les 3 instances (`tasky`, `tasky-yoan`, `tasky-davy`) puisqu'elles partagent
le même code.

## Logs d'usage

`location /` (dans la conf nginx) écrit dans `/var/log/nginx/tasky-usage.log`, au format
`<timestamp ISO> <prenom> <IP> "<requête>" <status>`. Seules les requêtes authentifiées
apparaissent (une redirection vers `/login` n'y figure pas). Rotation automatique via
`/etc/logrotate.d/nginx` (14 jours, compressé).

## Sudoers restreint

`fabien` a des droits `sudo` sans mot de passe, mais limités à un périmètre précis
(`/etc/sudoers.d/tasky-restart`) :
- `systemctl restart tasky` / `restart tasky-*` (n'importe quelle instance)
- `systemctl reload nginx`
- `/home/fabien/tasky/auth/root_helper.sh <prenom>` — script **root:root, mode 700**
  (fabien ne peut ni le lire ni le modifier), appelé uniquement par `add_user.sh`, qui
  fait les actions nécessitant root (créer l'unité systemd, recharger nginx).

Rien d'autre n'est autorisé sans mot de passe (`systemctl stop`, édition de fichiers
système, etc.) — volontairement, pour limiter les dégâts possibles en cas d'erreur.

## Backup

`backup/` est un **repo git séparé** (`github.com/fabien-arnaud/tasky-backup`, privé),
avec un cron horaire (`backup/backup.sh`) qui copie les données de **fabien uniquement**
(`data/fabien/tasks.csv` + `node_positions.json`) et les commit/push si elles ont changé.
`backup/restore.sh` permet de revenir à un ancien commit. Yoan et davy n'y sont pas inclus.

## Ce qui n'est jamais versionné (et pourquoi)

| Fichier/dossier | Raison |
|---|---|
| `data/` | Données de prod, propres à chacun |
| `app/venv/`, `auth/venv/` | Régénérable via `pip install -r requirements.txt` |
| `auth/users.json` | Hashs de mots de passe |
| `auth/secret_key` | Clé de signature des cookies de session |
| `auth/root_helper.sh` | Appartient à root, fabien ne peut même pas le lire |
| `backup/` (depuis le repo principal) | A son propre repo git séparé |
