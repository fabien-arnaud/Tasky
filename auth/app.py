import json
import os
import secrets
import tempfile

from flask import Flask, request, redirect, session, render_template_string, abort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, "users.json")
SECRET_KEY_PATH = os.path.join(BASE_DIR, "secret_key")

app = Flask(__name__)


def _load_secret_key():
    if not os.path.exists(SECRET_KEY_PATH):
        key = secrets.token_hex(32)
        fd = os.open(SECRET_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
    with open(SECRET_KEY_PATH) as f:
        return f.read().strip()


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)


def load_users():
    with open(USERS_PATH) as f:
        return json.load(f)


def save_users(users):
    fd, tmp_path = tempfile.mkstemp(dir=BASE_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, USERS_PATH)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


PAGE = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tasky – connexion</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #1e1e24; color: #eee;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  form { background: #2a2a33; padding: 2rem 2.5rem; border-radius: 10px; width: 280px; }
  h1 { font-size: 1.2rem; margin: 0 0 1.2rem; }
  label { display: block; font-size: 0.85rem; margin-bottom: 0.3rem; color: #aaa; }
  input { width: 100%; box-sizing: border-box; padding: 0.5rem; margin-bottom: 1rem;
          border-radius: 6px; border: 1px solid #444; background: #1e1e24; color: #eee; }
  button { width: 100%; padding: 0.6rem; border-radius: 6px; border: none;
           background: #4f8cff; color: white; font-size: 1rem; cursor: pointer; }
  button:hover { background: #3a75e0; }
  .error { color: #ff6b6b; font-size: 0.85rem; margin-bottom: 1rem; }
  .hint { color: #888; font-size: 0.8rem; margin-top: 1rem; }
</style>
</head>
<body>
<form method="post" action="/login">
  <h1>Tasky</h1>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if step == "name" %}
    <label for="name">Prénom</label>
    <input type="text" id="name" name="name" autofocus required>
    <input type="hidden" name="step" value="name">
    <input type="hidden" name="next" value="{{ next_url }}">
    <button type="submit">Continuer</button>
  {% elif step == "set" %}
    <label>{{ name }} — choisis ton mot de passe</label>
    <input type="password" name="password" placeholder="Mot de passe" required autofocus>
    <input type="password" name="confirm" placeholder="Confirme le mot de passe" required>
    <input type="hidden" name="name" value="{{ name }}">
    <input type="hidden" name="step" value="set">
    <input type="hidden" name="next" value="{{ next_url }}">
    <button type="submit">Créer mon compte</button>
    <div class="hint">Première connexion : ce mot de passe sera le tien.</div>
  {% elif step == "check" %}
    <label>{{ name }} — mot de passe</label>
    <input type="password" name="password" placeholder="Mot de passe" required autofocus>
    <input type="hidden" name="name" value="{{ name }}">
    <input type="hidden" name="step" value="check">
    <input type="hidden" name="next" value="{{ next_url }}">
    <button type="submit">Se connecter</button>
  {% endif %}
</form>
</body>
</html>
"""


def render(step, **kwargs):
    return render_template_string(PAGE, step=step, **kwargs)


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    if request.method == "GET":
        return render("name", next_url=next_url)

    step = request.form.get("step", "name")
    name = (request.form.get("name") or "").strip().lower()

    if step == "name":
        if not name:
            return render("name", next_url=next_url, error="Entre ton prénom.")
        users = load_users()
        if name not in users:
            return render("name", next_url=next_url, error="Prénom inconnu, contacte fabien.")
        if users[name].get("password_hash"):
            return render("check", name=name, next_url=next_url)
        return render("set", name=name, next_url=next_url)

    if step == "set":
        users = load_users()
        if name not in users:
            return render("name", next_url=next_url, error="Prénom inconnu, contacte fabien.")
        if users[name].get("password_hash"):
            # Quelqu'un a déjà créé le mot de passe entre-temps.
            return render("check", name=name, next_url=next_url)
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(password) < 4:
            return render("set", name=name, next_url=next_url, error="Mot de passe trop court (4 caractères min).")
        if password != confirm:
            return render("set", name=name, next_url=next_url, error="Les mots de passe ne correspondent pas.")
        from werkzeug.security import generate_password_hash
        users[name]["password_hash"] = generate_password_hash(password)
        save_users(users)
        session.clear()
        session["user"] = name
        session["sv"] = users[name].get("session_version", 0)
        session.permanent = True
        return redirect(next_url)

    if step == "check":
        users = load_users()
        if name not in users:
            return render("name", next_url=next_url, error="Prénom inconnu, contacte fabien.")
        password_hash = users[name].get("password_hash")
        if not password_hash:
            return render("set", name=name, next_url=next_url)
        from werkzeug.security import check_password_hash
        password = request.form.get("password") or ""
        if not check_password_hash(password_hash, password):
            return render("check", name=name, next_url=next_url, error="Mot de passe incorrect.")
        session.clear()
        session["user"] = name
        session["sv"] = users[name].get("session_version", 0)
        session.permanent = True
        return redirect(next_url)

    return render("name", next_url=next_url, error="Requête invalide.")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/verify")
def verify():
    user = session.get("user")
    if not user:
        abort(401)
    users = load_users()
    if user not in users:
        session.clear()
        abort(401)
    if session.get("sv") != users[user].get("session_version", 0):
        # Session révoquée (mot de passe réinitialisé depuis) : il faut se reconnecter.
        session.clear()
        abort(401)
    resp = app.response_class(status=200)
    resp.headers["X-User"] = user
    return resp
