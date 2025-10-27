import os, time, json, threading, subprocess, logging
from collections import deque
from flask import Flask, Response, render_template_string, stream_with_context, abort
from logging.handlers import RotatingFileHandler

# -----------------------------
# CONFIG
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
MAX_QUEUE_SIZE = 80
REFRESH_INTERVAL = 1800  # 30 min

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    
}

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
handler = RotatingFileHandler(LOG_PATH, maxBytes=3*1024*1024, backupCount=2)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)

app = Flask(__name__)
STREAMS, CACHE = {}, {}

# -----------------------------
# HTML UI
# -----------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Radio</title>
<style>
body{background:#000;color:#0f0;font-family:sans-serif;margin:0;padding:20px;text-align:center;}
.card{border:1px solid #0f0;border-radius:12px;margin:15px;padding:15px;display:inline-block;width:200px;background:#010;}
a{color:#0f0;text-decoration:none;}
h2{color:#0f0;margin-bottom:10px;}
.btn{display:inline-block;padding:8px 14px;border:1px solid #0f0;border-radius:8px;margin-top:8px;}
</style>
</head>
<body>
<h2>🎧 YouTube Radio</h2>
{% for name in playlists %}
<div class="card">
  <h3>{{name|capitalize}}</h3>
  <a href="/listen/{{name}}" class="btn">▶️ Play</a>
  <a href="/stream/{{name}}" class="btn">⬇️ MP3</a>
</div>
{% endfor %}
</body>
</html>
"""

PLAYER_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name|capitalize}} Radio</title>
<style>
body{background:#000;color:#0f0;font-family:sans-serif;text-align:center;margin:0;padding:20px;}
audio{width:90%;margin-top:20px;}
a{color:#0f0;text-decoration:none;}
</style>
</head>
<body>
<h2>🎶 {{name|capitalize}} Radio</h2>
<audio controls autoplay>
  <source src="/stream/{{name}}" type="audio/mpeg">
</audio>
<p><a href="/">⬅ Back</a></p>
</body>
</html>
"""

# -----------------------------
# CACHE HELPERS
# -----------------------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Cache load failed: {e}")
    return {}

def save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(CACHE, f)
    except Exception as e:
        logging.error(f"Cache save failed: {e}")

CACHE = load_cache()

# -----------------------------
# PLAYLIST HANDLING
# -----------------------------
def load_playlist_ids(name, force=False):
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]

    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist IDs...")
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if not e.get("private")]
        CACHE[name] = {"ids": ids, "time": now}
        save_cache()
        logging.info(f"[{name}] Cached {len(ids)} videos.")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("ids", [])

# -----------------------------
# STREAM WORKER
# -----------------------------
def stream_worker(name):
    stream = STREAMS[name]
    failed = set()

    while True:
        try:
            if not stream["IDS"]:
                stream["IDS"] = load_playlist_ids(name, True)
                stream["INDEX"] = 0
                failed.clear()
                time.sleep(2)
                continue

            # refresh after 30 min
            if time.time() - stream["LAST_REFRESH"] > REFRESH_INTERVAL:
                stream["IDS"] = load_playlist_ids(name, True)
                stream["INDEX"] = 0
                stream["LAST_REFRESH"] = time.time()
                failed.clear()

            vid = stream["IDS"][stream["INDEX"] % len(stream["IDS"])]
            stream["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ {url}")

            cmd = (
                f'yt-dlp -f bestaudio[ext=m4a]/bestaudio "{url}" '
                f'--cookies "{COOKIES_PATH}" -o - --quiet --no-warnings | '
                f'ffmpeg -loglevel quiet -i pipe:0 -f mp3 pipe:1'
            )

            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(stream["QUEUE"]) < MAX_QUEUE_SIZE:
                    stream["QUEUE"].append(chunk)

            proc.stdout.close()
            proc.wait()
        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(5)

# -----------------------------
# FLASK ROUTES
# -----------------------------
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
    if name not in STREAMS:
        abort(404)
    stream = STREAMS[name]

    def generate():
        while True:
            if stream["QUEUE"]:
                yield stream["QUEUE"].popleft()
            else:
                time.sleep(0.1)

    headers = {"Content-Type": "audio/mpeg"}
    return Response(stream_with_context(generate()), headers=headers)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {
            "IDS": load_playlist_ids(name),
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time()
        }
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()

    logging.info("🚀 YouTube Radio started!")
    logging.info(f"UI available at http://0.0.0.0:5000/")
    app.run(host="0.0.0.0", port=8000)