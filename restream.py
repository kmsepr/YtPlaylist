import os
import time
import json
import threading
import logging
import subprocess
from collections import deque
from flask import Flask, Response, render_template_string, abort

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"

# Multiple playlists with unique names
PLAYLISTS = {
    "malayalam": "https://youtube.com/playlist?list=PLYKzjRvMAychqR_ysgXiHAywPUsVw0AzE",
    }

# Holds stream states per playlist
STREAMS = {}  # { name: {VIDEOS, INDEX, QUEUE, LOCK, LAST_REFRESH} }

# -----------------------------
# HTML UI
# -----------------------------
HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Radio</title>
<style>
body { background:#000; color:#0f0; text-align:center; font-family:sans-serif; }
a { color:#0f0; display:block; padding:10px; border:1px solid #0f0;
    margin:10px; border-radius:10px; text-decoration:none; }
</style>
</head>
<body>
<h2>🎧 YouTube Continuous Radio</h2>
{% for name in playlists %}
<a href="/listen/{{name}}">▶️ {{name|capitalize}} Radio</a>
{% endfor %}
</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name|capitalize}} Radio</title></head>
<body style="background:#000;color:#0f0;text-align:center;font-family:sans-serif;">
<h3>🎶 {{name|capitalize}} Radio</h3>
<audio controls autoplay src="/stream/{{name}}" style="width:90%"></audio>
<p>YouTube Playlists</p>
</body>
</html>
"""

# -----------------------------
# CACHE MANAGEMENT
# -----------------------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")

CACHE = load_cache()

# -----------------------------
# PLAYLIST LOADING
# -----------------------------
def load_playlist(name, force=False):
    """Load or refresh playlist with caching"""
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < 1800:  # 30 min cache
        logging.info(f"[{name}] Using cached playlist ({len(cached['videos'])} videos)")
        return cached["videos"]

    url = PLAYLISTS[name]
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        videos = [f"https://www.youtube.com/watch?v={e['id']}" for e in data.get("entries", [])]
        CACHE[name] = {"videos": videos, "time": now}
        save_cache(CACHE)
        logging.info(f"[{name}] Loaded {len(videos)} videos (refreshed)")
        return videos
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("videos", [])

# -----------------------------
# CONTINUOUS STREAM THREAD
# -----------------------------
# -----------------------------
# CONTINUOUS STREAM THREAD WITH FULL LOGGING
# -----------------------------
def stream_worker(name):
    stream = STREAMS[name]
    while True:
        try:
            # Load playlist if empty
            if not stream["VIDEOS"]:
                logging.info(f"[{name}] Playlist empty, loading...")
                stream["VIDEOS"] = load_playlist(name, force=True)
                if not stream["VIDEOS"]:
                    logging.warning(f"[{name}] No videos available after loading, retrying in 60s...")
                    time.sleep(60)
                    continue

            # Refresh playlist every 30 minutes
            if time.time() - stream["LAST_REFRESH"] > 1800:
                logging.info(f"[{name}] Refreshing playlist...")
                refreshed = load_playlist(name, force=True)
                if refreshed:
                    stream["VIDEOS"] = refreshed
                    stream["LAST_REFRESH"] = time.time()
                    logging.info(f"[{name}] Playlist refreshed with {len(refreshed)} videos")
                else:
                    logging.warning(f"[{name}] Playlist refresh failed, keeping old list")

            # Get next video
            idx = stream["INDEX"] % len(stream["VIDEOS"])
            url = stream["VIDEOS"][idx]
            stream["INDEX"] += 1
            logging.info(f"[{name}] Now playing [{idx + 1}/{len(stream['VIDEOS'])}]: {url}")

            # Start yt-dlp
            cmd = [
                "yt-dlp", "-f", "bestaudio", "-o", "-", url,
                "--cookies", COOKIES_PATH
            ]
            logging.info(f"[{name}] Running command: {' '.join(cmd)}")

            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                while True:
                    chunk = proc.stdout.read(4096)
                    if chunk:
                        stream["QUEUE"].append(chunk)
                    else:
                        break

                # Capture yt-dlp stderr
                err = proc.stderr.read().decode()
                if err:
                    logging.error(f"[{name}] yt-dlp stderr:\n{err}")

            logging.info(f"[{name}] Track finished, moving to next... Queue size: {len(stream['QUEUE'])}")

        except Exception as e:
            logging.exception(f"[{name}] Stream worker encountered an exception: {e}")
            time.sleep(5)

# -----------------------------
# FLASK STREAM ENDPOINTS
# -----------------------------
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
    return Response(generate(), content_type="audio/mpeg")

@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS:
        abort(404)
    return render_template_string(PLAYER_HTML, name=name)

# -----------------------------
# MAIN STARTUP
# -----------------------------
if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {
            "VIDEOS": load_playlist(name),
            "INDEX": 0,
            "QUEUE": deque(),
            "LOCK": threading.Lock(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()

    logging.info("🎧 Multi-Playlist YouTube Radio started!")
    app.run(host="0.0.0.0", port=5000)