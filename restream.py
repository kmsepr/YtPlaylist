import os
import time
import random
import json
import threading
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context, redirect, url_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

# ==============================================================
# 🎶 YouTube Playlist Radio SECTION
# ==============================================================

LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
os.makedirs(DOWNLOAD_DIR := "/mnt/data/radio_cache", exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.getLogger().addHandler(handler)

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    "ca": "https://youtube.com/playlist?list=PLYKzjRvMAyci_W5xYyIXHBoR63eefUadL",
    "samastha": "https://youtube.com/playlist?list=PLgkREi1Wpr-XgNxocxs3iPj61pqMhi9bv",
    "hindi_playlist": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
}

# Default playback modes per playlist
DEFAULT_MODES = {
    "kas_ranker": "shuffle",
    "ca": "normal",
    "samastha": "reverse",
    "hindi_playlist": "normal",
}

STREAMS_RADIO = {}
MAX_QUEUE = 128
REFRESH_INTERVAL = 1800  # 30 min

def load_cache_radio():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE))
        except Exception:
            return {}
    return {}

def save_cache_radio(data):
    try:
        json.dump(data, open(CACHE_FILE, "w"))
    except Exception as e:
        logging.error(e)

CACHE_RADIO = load_cache_radio()

def load_playlist_ids_radio(name, force=False):
    now = time.time()
    cached = CACHE_RADIO.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]

    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist...")
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if "id" in e][::-1]
        CACHE_RADIO[name] = {"ids": ids, "time": now}
        save_cache_radio(CACHE_RADIO)
        logging.info(f"[{name}] Cached {len(ids)} videos.")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

def stream_worker_radio(name):
    s = STREAMS_RADIO[name]
    while True:
        try:
            ids = s["IDS"]
            if not ids:
                ids = load_playlist_ids_radio(name, True)
                s["IDS"] = ids
            if not ids:
                logging.warning(f"[{name}] No playlist ids found; sleeping...")
                time.sleep(10)
                continue

            vid = ids[s["INDEX"] % len(ids)]
            s["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ {url}")

            cmd = (
                f'yt-dlp -f "bestaudio/best" --cookies "{COOKIES_PATH}" '
                f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" '
                f'-o - --quiet --no-warnings "{url}" | '
                f'ffmpeg -loglevel quiet -i pipe:0 -ac 1 -ar 44100 -b:a 64k -f mp3 pipe:1'
            )

            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                while len(s["QUEUE"]) >= MAX_QUEUE:
                    time.sleep(0.05)
                s["QUEUE"].append(chunk)

            proc.wait()
            logging.info(f"[{name}] ✅ Track completed.")
            time.sleep(2)

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(5)

# ==============================================================
# 🌐 Web Interface
# ==============================================================

PLAYLIST_ORDER = {name: DEFAULT_MODES.get(name, "normal") for name in PLAYLISTS}

def reorder_playlist(name, mode="normal"):
    if name not in CACHE_RADIO or "ids" not in CACHE_RADIO[name]:
        return
    ids = CACHE_RADIO[name]["ids"]
    if mode == "shuffle":
        random.shuffle(ids)
    elif mode == "reverse":
        ids = list(reversed(ids))
    elif mode == "normal":
        ids = load_playlist_ids_radio(name, True)
    CACHE_RADIO[name]["ids"] = ids
    CACHE_RADIO[name]["time"] = time.time()
    save_cache_radio(CACHE_RADIO)
    PLAYLIST_ORDER[name] = mode
    logging.info(f"[{name}] Playlist set to {mode} mode with {len(ids)} videos.")

def refresh_stream_ids(name):
    if name in STREAMS_RADIO and name in CACHE_RADIO:
        STREAMS_RADIO[name]["IDS"] = CACHE_RADIO[name]["ids"]
        STREAMS_RADIO[name]["INDEX"] = 0
        logging.info(f"[{name}] Stream refreshed with reordered playlist.")

@app.route("/")
def home():
    playlists = list(PLAYLISTS.keys())
    html = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎧 YouTube Radio</title>
<style>
body{background:#000;color:#0f0;font-family:Arial,Helvetica,sans-serif;text-align:center;margin:0;padding:16px}
a,button{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:8px 12px;margin:4px;border-radius:8px;background:transparent;cursor:pointer}
a:hover,button:hover{background:#0f0;color:#000}
.card{border:1px solid #0f0;border-radius:10px;padding:12px;margin:12px}
</style></head><body>
<h2>🎶 YouTube Playlist Radio</h2>
{% for p in playlists %}
<div class="card">
  <h3>{{p|capitalize}}</h3>
  <p>Mode: <b>{{playlist_modes[p]}}</b></p>
  <a href="/listen/{{p}}">▶ Listen / Download</a> |
  <a href="/stream/{{p}}">🎧 Stream Live</a><br><br>
  <form action="/mode/{{p}}" method="post">
    <button name="mode" value="normal">Normal</button>
    <button name="mode" value="shuffle">Shuffle</button>
    <button name="mode" value="reverse">Reverse</button>
  </form>
</div>
{% endfor %}
</body></html>"""
    return render_template_string(html, playlists=playlists, playlist_modes=PLAYLIST_ORDER)

@app.route("/listen/<name>")
def listen_radio_download(name):
    if name not in STREAMS_RADIO:
        abort(404)
    s = STREAMS_RADIO[name]
    def gen():
        while True:
            if s["QUEUE"]:
                yield s["QUEUE"].popleft()
            else:
                time.sleep(0.05)
    headers = {"Content-Disposition": f"attachment; filename={name}.mp3"}
    return Response(stream_with_context(gen()), mimetype="audio/mpeg", headers=headers)

@app.route("/stream/<name>")
def stream_audio(name):
    if name not in STREAMS_RADIO:
        abort(404)
    s = STREAMS_RADIO[name]
    def gen():
        while True:
            if s["QUEUE"]:
                yield s["QUEUE"].popleft()
            else:
                time.sleep(0.05)
    return Response(stream_with_context(gen()), mimetype="audio/mpeg")

@app.route("/mode/<name>", methods=["POST"])
def change_mode(name):
    from flask import request
    if name not in PLAYLISTS:
        abort(404)
    mode = request.form.get("mode", "normal")
    if mode not in ["shuffle", "reverse", "normal"]:
        return "❌ Invalid mode"
    reorder_playlist(name, mode)
    refresh_stream_ids(name)
    return redirect(url_for("home"))

@app.route("/status")
def show_status():
    html = "<h3>🎶 Playlist Modes</h3><ul>"
    for k, v in PLAYLIST_ORDER.items():
        count = len(STREAMS_RADIO[k]["IDS"])
        html += f"<li>{k}: <b>{v}</b> ({count} tracks)</li>"
    html += "</ul>"
    return html

# ==============================================================
# 🚀 START SERVER
# ==============================================================

if __name__ == "__main__":
    for pname in PLAYLISTS:
        mode = DEFAULT_MODES.get(pname, "normal")
        ids = load_playlist_ids_radio(pname)
        CACHE_RADIO[pname] = {"ids": ids, "time": time.time()}
        if mode == "shuffle":
            random.shuffle(ids)
        elif mode == "reverse":
            ids = list(reversed(ids))
        CACHE_RADIO[pname]["ids"] = ids
        STREAMS_RADIO[pname] = {
            "IDS": ids,
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time(),
        }
        PLAYLIST_ORDER[pname] = mode
        logging.info(f"[{pname}] Initialized in {mode} mode ({len(ids)} tracks).")
        threading.Thread(target=stream_worker_radio, args=(pname,), daemon=True).start()

    logging.info("🚀 YouTube Playlist Radio server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)
