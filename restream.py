import os
import time
import json
import threading
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from flask import Flask, Response, abort, stream_with_context
import requests
import random

# ==============================================================
# ⚙️ Setup
# ==============================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
os.makedirs(DOWNLOAD_DIR := "/mnt/data/radio_cache", exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.getLogger().addHandler(handler)

# ==============================================================
# 🎶 YouTube Playlists
# ==============================================================

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    "ca": "https://youtube.com/playlist?list=PLYKzjRvMAyci_W5xYyIXHBoR63eefUadL",
    "studyiq": "https://youtube.com/playlist?list=PLMDetQy00TVmlsN2dnS_ybPdmAf02m9Y8",
    "hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
    "samastha": "https://youtube.com/playlist?list=PLgkREi1Wpr-XgNxocxs3iPj61pqMhi9bv",
}

PLAYLIST_SETTINGS = {
    "kas_ranker": {"mode": "reverse"},
    "ca": {"mode": "normal"},
    "studyiq": {"mode": "reverse"},
    "hindi": {"mode": "shuffle"},
    "samastha": {"mode": "normal"},
}

# ==============================================================
# 📦 Caching & State
# ==============================================================

STREAMS_RADIO = {}
MAX_QUEUE = 128
REFRESH_INTERVAL = 1800  # 30 minutes

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

# ==============================================================
# 🎧 Playlist Loader
# ==============================================================

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
        ids = [e["id"] for e in data.get("entries", []) if "id" in e]

        mode = PLAYLIST_SETTINGS.get(name, {}).get("mode", "normal")
        if mode == "reverse":
            ids = ids[::-1]
        elif mode == "shuffle":
            random.shuffle(ids)

        CACHE_RADIO[name] = {"ids": ids, "time": now}
        save_cache_radio(CACHE_RADIO)
        logging.info(f"[{name}] Cached {len(ids)} videos ({mode} mode).")
        return ids

    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

# ==============================================================
# 🧠 Streaming Worker
# ==============================================================

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
                f'yt-dlp -f "bestaudio[ext=m4a]/bestaudio/best" --cookies "{COOKIES_PATH}" '
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
# 🌐 Flask Routes
# ==============================================================

@app.route("/listen/<name>")
def listen_radio(name):
    if name not in STREAMS_RADIO:
        abort(404)
    s = STREAMS_RADIO[name]

    def gen():
        while True:
            if s["QUEUE"]:
                yield s["QUEUE"].popleft()
            else:
                time.sleep(0.05)

    headers = {"Content-Disposition": f"inline; filename={name}.mp3"}
    return Response(stream_with_context(gen()), mimetype="audio/mpeg", headers=headers)

# ==============================================================
# 💤 Keep-Alive (Prevents Autosleep)
# ==============================================================

def keep_alive():
    while True:
        try:
            requests.get("http://localhost:8000/listen/ca", timeout=5)
        except:
            pass
        time.sleep(240)  # Ping every 4 minutes

# ==============================================================
# 🚀 START SERVER
# ==============================================================

if __name__ == "__main__":
    for pname in PLAYLISTS:
        STREAMS_RADIO[pname] = {
            "IDS": load_playlist_ids_radio(pname),
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker_radio, args=(pname,), daemon=True).start()

    threading.Thread(target=keep_alive, daemon=True).start()
    logging.info("🚀 YouTube Playlist Radio server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)
