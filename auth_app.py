#!/usr/bin/env python3
"""Cabinet Jaubert — page Connexions (auth). The lawyer enters his own API keys /
credentials; they are stored ONLY on this server (his box), validated live, and
used by his Pat. Supports single-key (Anthropic, OpenAI) and multi-field
(Légifrance: client_id + secret) connectors. French, passcode-gated."""
import os, secrets as pysecrets, imaplib, hashlib, time
from flask import Flask, request, redirect, session, render_template_string, url_for, flash
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(BASE, "secrets")
os.makedirs(SECRETS, exist_ok=True)
ACCESS_PW = os.environ.get("CONNECT_PASSWORD", "")
PORT = int(os.environ.get("PORT", "8780"))

def _val_anthropic(v):
    try:
        return requests.get("https://api.anthropic.com/v1/models",
            headers={"x-api-key": v["key"], "anthropic-version": "2023-06-01"}, timeout=15).status_code == 200
    except Exception:
        return False

def _val_openai(v):
    try:
        return requests.get("https://api.openai.com/v1/models",
            headers={"Authorization": "Bearer " + v["key"]}, timeout=15).status_code == 200
    except Exception:
        return False

def _val_legifrance(v):
    try:
        r = requests.post("https://oauth.piste.gouv.fr/api/oauth/token", data={
            "grant_type": "client_credentials", "client_id": v["id"],
            "client_secret": v["secret"], "scope": "openid"}, timeout=20)
        return r.status_code == 200 and "access_token" in r.json()
    except Exception:
        return False

def _val_email_pro(v):
    # OVH-hosted mailbox (avocats-jaubert.com) — verify by an IMAP SSL login.
    try:
        host = (v.get("host") or "ssl0.ovh.net").strip()
        m = imaplib.IMAP4_SSL(host, 993, timeout=15)
        m.login(v["email"], v["password"]); m.logout(); return True
    except Exception:
        return False

def _val_gmail(v):
    # Gmail — requires a 16-char App Password (not the normal password) over IMAP SSL.
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15)
        m.login(v["email"], (v["password"] or "").replace(" ", "")); m.logout(); return True
    except Exception:
        return False

def _val_ovh(v):
    # OVHcloud API (EU): signed GET /me. Uses OVH server time to avoid clock skew.
    try:
        base = "https://eu.api.ovh.com/1.0"
        ts = requests.get(base + "/auth/time", timeout=10).text.strip()
        url = base + "/me"
        sig = "$1$" + hashlib.sha1(
            "+".join([v["secret"], v["consumer"], "GET", url, "", ts]).encode()).hexdigest()
        r = requests.get(url, headers={
            "X-Ovh-Application": v["app"], "X-Ovh-Consumer": v["consumer"],
            "X-Ovh-Timestamp": ts, "X-Ovh-Signature": sig}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False

SERVICES = [
    {"id": "anthropic", "label": "Clé API Anthropic (Claude)", "role": "Fait fonctionner votre assistant Pat.",
     "help": "console.anthropic.com → Settings → API Keys. Ce n'est PAS l'abonnement Claude Pro — il faut une clé API (facturation à l'usage).",
     "url": "https://console.anthropic.com/settings/keys",
     "fields": [{"n": "key", "ph": "sk-ant-…", "t": "password"}], "val": _val_anthropic},
    {"id": "openai", "label": "Clé API OpenAI (ChatGPT)", "role": "Transcription vocale, génération d'images, modèles GPT.",
     "help": "platform.openai.com/api-keys.", "url": "https://platform.openai.com/api-keys",
     "fields": [{"n": "key", "ph": "sk-…", "t": "password"}], "val": _val_openai},
    {"id": "legifrance", "label": "Légifrance & Conseil d'État", "role": "Recherche juridique : codes, jurisprudence (Cassation), Conseil d'État (Ariane).",
     "help": "Gratuit. Créez un compte sur piste.gouv.fr → une application → abonnez-vous à l'API « Légifrance » et ACCEPTEZ les CGU dans le portail → copiez l'Identifiant client (client_id) et la Clé secrète.",
     "url": "https://piste.gouv.fr/",
     "fields": [{"n": "id", "ph": "Identifiant client (client_id)", "t": "text"},
                {"n": "secret", "ph": "Clé secrète (client_secret)", "t": "password"}],
     "val": _val_legifrance},
    {"id": "email_pro", "label": "E-mail professionnel (avocats-jaubert.com)",
     "role": "Permet à votre assistant de lire et rechercher vos e-mails professionnels.",
     "help": "Boîte hébergée chez OVHcloud (serveur IMAP ssl0.ovh.net). Saisissez l'adresse complète et le mot de passe de la boîte.",
     "url": "https://www.ovh.com/manager/#/web/email",
     "fields": [{"n": "email", "ph": "d.jaubert@avocats-jaubert.com", "t": "text", "default": "d.jaubert@avocats-jaubert.com"},
                {"n": "host", "ph": "ssl0.ovh.net", "t": "text", "default": "ssl0.ovh.net"},
                {"n": "password", "ph": "Mot de passe de la boîte", "t": "password"}],
     "val": _val_email_pro},
    {"id": "gmail", "label": "Gmail (didier.jaubert@gmail.com)",
     "role": "Permet à votre assistant de lire et rechercher votre Gmail.",
     "help": "Activez la validation en 2 étapes, puis créez un « mot de passe d'application » (Google → Sécurité) et collez-le ici — PAS votre mot de passe Google habituel.",
     "url": "https://myaccount.google.com/apppasswords",
     "fields": [{"n": "email", "ph": "didier.jaubert@gmail.com", "t": "text", "default": "didier.jaubert@gmail.com"},
                {"n": "password", "ph": "Mot de passe d'application (16 caractères)", "t": "password"}],
     "val": _val_gmail},
    {"id": "ovhcloud", "label": "OVHcloud (domaine avocats-jaubert.com)",
     "role": "Gestion du domaine et des e-mails : DNS, mise en ligne du site, redirections.",
     "help": "Créez un jeu de clés API sur api.ovh.com/createToken (droits GET/POST/PUT/DELETE sur /domain et /email), puis copiez les trois clés. Endpoint : ovh-eu.",
     "url": "https://api.ovh.com/createToken/",
     "fields": [{"n": "app", "ph": "Application Key", "t": "text"},
                {"n": "secret", "ph": "Application Secret", "t": "password"},
                {"n": "consumer", "ph": "Consumer Key", "t": "password"}],
     "val": _val_ovh},
]
SVC = {s["id"]: s for s in SERVICES}
SOON = [("microsoft", "Outlook & OneDrive", "Connexion Microsoft (e-mails + fichiers)"),
        ("jarvis", "Jarvis Legal", "Votre logiciel de gestion de cabinet")]

app = Flask(__name__)
app.secret_key = pysecrets.token_hex(16)

def fpath(sid, fname): return os.path.join(SECRETS, sid + "_" + fname)
def connected(s): return all(os.path.exists(fpath(s["id"], f["n"])) for f in s["fields"])
def tail(s):
    last = s["fields"][-1]["n"]; p = fpath(s["id"], last)
    return open(p).read().strip()[-4:] if os.path.exists(p) else ""

@app.before_request
def gate():
    if not ACCESS_PW or request.endpoint in ("login", "static"):
        return
    if not session.get("ok"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if not ACCESS_PW:
        return redirect("/")
    if request.method == "POST":
        if request.form.get("pw") == ACCESS_PW:
            session["ok"] = True; return redirect("/")
        flash("Code incorrect")
    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/save", methods=["POST"])
def save():
    s = SVC.get(request.form.get("service"))
    if not s:
        flash("Service inconnu."); return redirect("/")
    vals = {f["n"]: (request.form.get(f["n"]) or "").strip() for f in s["fields"]}
    if not all(vals.values()):
        flash("Veuillez remplir tous les champs."); return redirect("/")
    if not s["val"](vals):
        flash(f"❌ Identifiants {s['label']} refusés par le fournisseur — vérifiez la saisie.")
        return redirect("/")
    for f in s["fields"]:
        p = fpath(s["id"], f["n"])
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, vals[f["n"]].encode()); os.close(fd)
    flash(f"✓ {s['label']} connectée et vérifiée.")
    return redirect("/")

@app.route("/remove", methods=["POST"])
def remove():
    s = SVC.get(request.form.get("service"))
    if s:
        for f in s["fields"]:
            try: os.remove(fpath(s["id"], f["n"]))
            except OSError: pass
    flash("Connexion supprimée.")
    return redirect("/")

@app.route("/")
def home():
    rows = [{**s, "connected": connected(s), "tail": tail(s)} for s in SERVICES]
    return render_template_string(HOME_HTML, rows=rows, soon=SOON)

LOGIN_HTML = """<!doctype html><html lang=fr><meta charset=utf-8><title>Connexions · Cabinet Jaubert</title>
<style>body{font-family:-apple-system,Arial;background:#0f1220;color:#eee;display:grid;place-items:center;height:100vh;margin:0}
form{background:#1b2036;padding:32px;border-radius:14px;width:300px}h2{margin:0 0 14px}
input{width:100%;padding:11px;margin:8px 0;border-radius:8px;border:1px solid #333;background:#0f1220;color:#eee}
button{width:100%;padding:11px;border:0;border-radius:8px;background:#1f3a8a;color:#fff;font-weight:600;cursor:pointer}
.f{color:#f7a;font-size:13px}</style>
<form method=post><h2>🔒 Connexions</h2>
{% with m=get_flashed_messages() %}{% for x in m %}<div class=f>{{x}}</div>{% endfor %}{% endwith %}
<input type=password name=pw autofocus placeholder="Code d'accès"><button>Entrer</button></form></html>"""

HOME_HTML = """<!doctype html><html lang=fr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Connexions · Cabinet Jaubert</title>
<style>
:root{--bg:#0f1220;--card:#1b2036;--mut:#8a86a8;--acc:#1f3a8a;--acc2:#3454c4;--line:#262b45}
*{box-sizing:border-box}body{font-family:-apple-system,"Helvetica Neue",Arial;background:var(--bg);color:#eee;margin:0}
.wrap{max-width:720px;margin:0 auto;padding:30px 18px 60px}
h1{font-size:22px;margin:0 0 2px}.sub{color:var(--mut);font-size:13.5px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.name{font-weight:700;font-size:15.5px}.role{color:var(--mut);font-size:12.5px;margin-top:2px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}.on{background:#37c66b}.off{background:#6a6481}
.st{font-size:12.5px;color:var(--mut)}
.help{color:var(--mut);font-size:12px;margin:10px 0 8px;line-height:1.5}.help a{color:#9db4ff}
form.k{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}form.k input{flex:1 1 100%;padding:10px;border-radius:8px;border:1px solid #333;background:var(--bg);color:#eee;font-size:14px}
button{border:0;border-radius:8px;padding:10px 16px;font-weight:600;font-size:13px;cursor:pointer}
.save{background:var(--acc);color:#fff}.save:hover{background:var(--acc2)}.rm{background:#3a2f5e;color:#cdbff5}
.flash{background:#16321f;color:#7fe0a3;padding:10px 14px;border-radius:9px;margin-bottom:16px;font-size:13.5px}
.flash.e{background:#3a1d1d;color:#ffb3b3}
.soon{opacity:.6}.soon .tag{font-size:11px;color:#bfb8e6;background:#2a2350;padding:3px 9px;border-radius:999px}
.logout{float:right;color:var(--mut);font-size:12px;text-decoration:none}
</style></head><body><div class=wrap>
<a class=logout href="/logout">déconnexion</a>
<h1>🔌 Connexions</h1>
<div class=sub>Connectez vos services à votre assistant. Tout reste sur votre serveur privé — rien n'est partagé.</div>
{% with msgs=get_flashed_messages() %}{% for m in msgs %}<div class="flash {{ 'e' if '❌' in m or 'incorrect' in m or 'refus' in m else '' }}">{{m}}</div>{% endfor %}{% endwith %}
{% for s in rows %}
<div class=card>
  <div class=top>
    <div><div class=name>{{s.label}}</div><div class=role>{{s.role}}</div></div>
    <div class=st><span class="dot {{ 'on' if s.connected else 'off' }}"></span>{{ 'Connectée · …'+s.tail if s.connected else 'Non connectée' }}</div>
  </div>
  <div class=help>{{s.help}} <a href="{{s.url}}" target=_blank rel=noopener>Obtenir les identifiants →</a></div>
  <form class=k method=post action="/save"><input type=hidden name=service value="{{s.id}}">
    {% for f in s.fields %}<input type="{{f.t}}" name="{{f.n}}" placeholder="{{f.ph}}" value="{{ f.default|default('') }}" autocomplete=off>{% endfor %}
    <button class=save>{{ 'Mettre à jour' if s.connected else 'Connecter' }}</button></form>
  {% if s.connected %}<form method=post action="/remove" style="margin-top:8px"><input type=hidden name=service value="{{s.id}}"><button class=rm>Supprimer</button></form>{% endif %}
</div>
{% endfor %}
<div class=sub style="margin-top:26px">Prochainement</div>
{% for sid,name,desc in soon %}
<div class="card soon"><div class=top><div><div class=name>{{name}}</div><div class=role>{{desc}}</div></div><span class=tag>Bientôt</span></div></div>
{% endfor %}
</div></body></html>"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT)
