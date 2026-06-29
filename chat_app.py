#!/usr/bin/env python3
"""Cabinet Jaubert — Assistant (chat web). Wraps the client's Hermes Pat
(`hermes -p jaubert`), one message at a time, with per-browser conversation
memory via Hermes named sessions. French UI, passcode-gated. Runs on his box."""
import os, subprocess, secrets as pysecrets, threading, re
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, flash

HERMES = "/home/ubuntu/.local/bin/hermes"
PROFILE = "jaubert"
PORT = int(os.environ.get("PORT", "8781"))
ACCESS_PW = os.environ.get("CONNECT_PASSWORD", "")
TIMEOUT = 180

app = Flask(__name__)
app.secret_key = pysecrets.token_hex(16)
LOCK = threading.Lock()

def _sid():
    s = request.cookies.get("sid")
    return s if s and re.fullmatch(r"[0-9a-f]{16}", s) else None

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

@app.route("/chat", methods=["POST"])
def chat():
    msg = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not msg:
        return jsonify({"reply": ""})
    sid = _sid() or pysecrets.token_hex(8)
    sess_name = "web-" + sid
    env = dict(os.environ, HOME="/home/ubuntu",
               PATH="/home/ubuntu/.local/bin:/home/ubuntu/.hermes/bin:/usr/local/bin:/usr/bin:/bin")
    cmd = [HERMES, "-p", PROFILE, "-c", sess_name, "-z", msg]
    try:
        out = subprocess.run(cmd, cwd="/home/ubuntu", env=env, capture_output=True,
                             text=True, timeout=TIMEOUT)
        reply = (out.stdout or "").strip() or (out.stderr or "").strip() or "(réponse vide)"
    except subprocess.TimeoutExpired:
        reply = "⏱️ La réponse a pris trop de temps. Réessayez ou reformulez."
    except Exception as e:
        reply = "⚠️ Erreur : " + str(e)
    resp = jsonify({"reply": reply})
    resp.set_cookie("sid", sid, max_age=60*60*24*30, httponly=True, samesite="Lax")
    return resp

@app.route("/new", methods=["POST"])
def new():
    # new conversation = new sid cookie (fresh Hermes session)
    resp = jsonify({"ok": True})
    resp.set_cookie("sid", pysecrets.token_hex(8), max_age=60*60*24*30, httponly=True, samesite="Lax")
    return resp

@app.route("/")
def home():
    return render_template_string(HOME_HTML)

LOGIN_HTML = """<!doctype html><html lang=fr><meta charset=utf-8><title>Assistant · Cabinet Jaubert</title>
<style>body{font-family:-apple-system,Arial;background:#0f1220;color:#eee;display:grid;place-items:center;height:100vh;margin:0}
form{background:#1b2036;padding:32px;border-radius:14px;width:300px}h2{margin:0 0 14px}
input{width:100%;padding:11px;margin:8px 0;border-radius:8px;border:1px solid #333;background:#0f1220;color:#eee}
button{width:100%;padding:11px;border:0;border-radius:8px;background:#1f3a8a;color:#fff;font-weight:600;cursor:pointer}
.f{color:#f7a;font-size:13px}</style>
<form method=post><h2>⚖️ Assistant · Cabinet Jaubert</h2>
{% with m=get_flashed_messages() %}{% for x in m %}<div class=f>{{x}}</div>{% endfor %}{% endwith %}
<input type=password name=pw autofocus placeholder="Code d'accès"><button>Entrer</button></form></html>"""

HOME_HTML = """<!doctype html><html lang=fr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Assistant · Cabinet Jaubert</title>
<style>
:root{--bg:#0f1220;--card:#1b2036;--mut:#8a86a8;--acc:#1f3a8a;--acc2:#3454c4;--me:#26346b;--line:#262b45}
*{box-sizing:border-box}body{font-family:-apple-system,"Helvetica Neue",Arial;background:var(--bg);color:#eee;margin:0;height:100vh;display:flex;flex-direction:column}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between}
header h1{font-size:16px;margin:0}.sub{color:var(--mut);font-size:12px}
#new{background:#2a2350;color:#cdbff5;border:0;border-radius:8px;padding:7px 12px;font-size:12px;font-weight:600;cursor:pointer}
#log{flex:1;overflow-y:auto;padding:18px;max-width:820px;width:100%;margin:0 auto}
.msg{margin:0 0 14px;display:flex}.msg.me{justify-content:flex-end}
.bubble{padding:11px 14px;border-radius:13px;max-width:84%;white-space:pre-wrap;word-wrap:break-word;line-height:1.55;font-size:14.5px}
.me .bubble{background:var(--me);color:#eaf0ff;border-bottom-right-radius:4px}
.pat .bubble{background:var(--card);border-bottom-left-radius:4px}
.think{color:var(--mut);font-size:13px;font-style:italic}
form{display:flex;gap:9px;padding:14px 18px;border-top:1px solid var(--line);max-width:820px;width:100%;margin:0 auto}
#q{flex:1;padding:12px 14px;border-radius:11px;border:1px solid #333;background:var(--card);color:#eee;font-size:15px;resize:none;max-height:140px}
button.send{background:var(--acc);color:#fff;border:0;border-radius:11px;padding:0 20px;font-weight:600;cursor:pointer}button.send:hover{background:var(--acc2)}
.hint{color:var(--mut);font-size:12.5px;text-align:center;margin:30px auto;max-width:560px;line-height:1.55}
.logout{color:var(--mut);font-size:12px;text-decoration:none}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#37c66b;margin-right:6px}
</style></head><body>
<header><div><h1>⚖️ Pat <span class=sub>· assistant du Cabinet Jaubert</span></h1></div>
<div><a class=logout href="/logout" style="margin-right:12px">déconnexion</a><button id=new>＋ Nouvelle conversation</button></div></header>
<div id=log><div class=hint><span class=dot></span>Connecté à votre assistant, sur votre propre serveur.<br>
Posez-lui une question — rédaction, recherche, synthèse d'un dossier. Tout reste confidentiel.</div></div>
<form id=f><textarea id=q rows=1 placeholder="Écrivez à Pat…" autofocus></textarea><button class=send>Envoyer</button></form>
<script>
const log=document.getElementById('log'),q=document.getElementById('q'),f=document.getElementById('f');
function add(cls){const m=document.createElement('div');m.className='msg '+cls;const b=document.createElement('div');b.className='bubble';m.appendChild(b);log.appendChild(m);log.scrollTop=log.scrollHeight;return b;}
q.addEventListener('input',()=>{q.style.height='auto';q.style.height=q.scrollHeight+'px';});
q.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();f.requestSubmit();}});
document.getElementById('new').onclick=async()=>{await fetch('/new',{method:'POST'});log.innerHTML='';location.reload();};
f.onsubmit=async e=>{e.preventDefault();const text=q.value.trim();if(!text)return;
add('me').textContent=text;q.value='';q.style.height='auto';
const btn=f.querySelector('button');btn.disabled=true;
const tb=add('pat');tb.innerHTML='<span class=think>Pat réfléchit…</span>';
try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
const d=await r.json();tb.textContent=d.reply||'(réponse vide)';}
catch(err){tb.textContent='⚠️ '+err;}
log.scrollTop=log.scrollHeight;btn.disabled=false;q.focus();};
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)
