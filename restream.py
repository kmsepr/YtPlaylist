import os, time, json, threading, subprocess, logging
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context
from logging.handlers import RotatingFileHandler

# ---------------- CONFIG ----------------
LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
DOWNLOAD_DIR = "/mnt/data/radio_cache"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)

app = Flask(__name__)

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
}

STREAMS = {}
REFRESH_INTERVAL = 1800  # 30 min
DOWNLOAD_INTERVAL = 3600  # 1 hour

# ---------------- HTML ----------------
HOME_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>YouTube Radio</title><style>
body{background:#000;color:#0f0;text-align:center;font-family:sans-serif}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:10px;display:block;border-radius:8px}
</style></head><body>
<h2>🎧 YouTube Radio</h2>
{% for n in playlists %}
<a href="/listen/{{n}}">▶️ {{n|capitalize}}</a>
{% endfor %}
</body></html>"""

PLAYER_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{name|capitalize}}</title></head>
<body style="background:#000;color:#0f0;text-align:center;font-family:sans-serif">
<h3>🎶 {{name|capitalize}} Radio</h3>
<audio controls autoplay style="width:90%;margin-top:20px">
  <source src="/stream/{{name}}" type="audio/mpeg">
</audio>
<p>Now playing cached MP3 (updates hourly)</p>
</body></html>"""

# ---------------- CACHE ----------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE))
        except Exception:
            return {}
    return {}

def save_cache(data):
    try:
        json.dump(data, open(CACHE_FILE, "w"))
    except Exception as e:
        logging.error(e)

CACHE = load_cache()

# ---------------- PLAYLIST LOADER ----------------
def load_playlist_ids(name, force=False):
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]
    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist...")
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if "id" in e]
        ids.reverse()  # latest first
        CACHE[name] = {"ids": ids, "time": now}
        save_cache(CACHE)
        logging.info(f"[{name}] Cached {len(ids)} videos (latest first).")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

# ---------------- STREAM WORKER ----------------
def stream_worker(name):
    stream = STREAMS[name]
    while True:
        try:
            ids = stream["IDS"]
            if not ids:
                ids = load_playlist_ids(name, True)
                stream["IDS"] = ids
            if not ids:
                logging.warning(f"[{name}] No videos found, retrying...")
                time.sleep(60)
                continue

            vid = ids[stream["INDEX"] % len(ids)]
            stream["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            outfile = os.path.join(DOWNLOAD_DIR, f"{name}.mp3")

            logging.info(f"[{name}] ⬇️ Downloading new track: {url}")
            cmd = [
                "yt-dlp", "-f", "bestaudio/best", "--cookies", COOKIES_PATH,
                "--extract-audio", "--audio-format", "mp3",
                "-o", outfile, url
            ]
            subprocess.run(cmd, check=True)
            logging.info(f"[{name}] ✅ Track downloaded to {outfile}")

            stream["CURRENT_FILE"] = outfile
            stream["LAST_REFRESH"] = time.time()

            # Serve this one for 1 hour
            for _ in range(int(DOWNLOAD_INTERVAL / 10)):
                time.sleep(10)
                # Refresh playlist occasionally
                if time.time() - CACHE.get(name, {}).get("time", 0) > REFRESH_INTERVAL:
                    load_playlist_ids(name, True)

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(30)

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS:
        abort(404)
    return render_template_string(PLAYER_HTML, name=name)

@app.route("/stream/<name>")
def stream_audio(name):
    if name not in STREAMS or "CURRENT_FILE" not in STREAMS[name]:
        abort(404)
    path = STREAMS[name]["CURRENT_FILE"]

    def generate():
        while True:  # continuous loop playback
            with open(path, "rb") as f:
                chunk = f.read(4096)
                while chunk:
                    yield chunk
                    chunk = f.read(4096)
    return Response(stream_with_context(generate()), mimetype="audio/mpeg")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {
            "IDS": load_playlist_ids(name),
            "INDEX": 0,
            "CURRENT_FILE": None,
            "LAST_REFRESH": 0,
        }
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()

    logging.info("🚀 YouTube Radio started successfully!")
    logging.info("🌐 Open http://0.0.0.0:8000 to access the UI.")
    app.run(host="0.0.0.0", port=8000)