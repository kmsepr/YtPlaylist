import os
import json
import random
import subprocess
import threading
import logging
from collections import deque
from flask import Flask, Response, request, redirect, render_template_string, abort
from logging.handlers import RotatingFileHandler

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=1)
logging.basicConfig(handlers=[handler], level=logging.INFO, format="%(asctime)s - %(message)s")

app = Flask(__name__)

PLAYLIST_FILE = "playlists.json"
CACHE = {}
PLAY_QUEUE = {}
LOCK = threading.Lock()


def load_playlists():
    if os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "r") as f:
            return json.load(f)
    return {}


def save_playlists(playlists):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(playlists, f)


PLAYLISTS = load_playlists()

# -----------------------------
# BACKGROUND FETCHER
# -----------------------------
def fetch_playlist_videos(name, url):
    logging.info(f"[{name}] Refreshing playlist IDs...")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--get-id", url],
            capture_output=True, text=True, timeout=60
        )
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if ids:
            with LOCK:
                CACHE[name] = deque(ids)
            logging.info(f"[{name}] Loaded {len(ids)} video IDs successfully")
    except Exception as e:
        logging.error(f"[{name}] Error fetching videos: {e}")


def background_refresh():
    while True:
        for name, url in PLAYLISTS.items():
            fetch_playlist_videos(name, url)
        logging.info("All playlists refreshed. Sleeping for 2 hours...")
        threading.Event().wait(7200)


threading.Thread(target=background_refresh, daemon=True).start()

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    playlists = load_playlists()
    return render_template_string(HOME_HTML, playlists=playlists)


@app.route("/add_playlist", methods=["POST"])
def add_playlist():
    name = request.form["name"].strip()
    url = request.form["url"].strip()
    if "&" in url:  # auto remove extra params
        url = url.split("&")[0]

    if name and url:
        PLAYLISTS[name] = url
        save_playlists(PLAYLISTS)
        fetch_playlist_videos(name, url)
    return redirect("/")


@app.route("/delete/<name>")
def delete_playlist(name):
    if name in PLAYLISTS:
        PLAYLISTS.pop(name)
        save_playlists(PLAYLISTS)
        CACHE.pop(name, None)
    return redirect("/")


@app.route("/shuffle/<name>")
def shuffle_playlist(name):
    if name in CACHE:
        with LOCK:
            ids = list(CACHE[name])
            random.shuffle(ids)
            CACHE[name] = deque(ids)
    return redirect("/")


@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS:
        abort(404)
    return render_template_string(PLAYER_HTML, name=name)


@app.route("/stream/<name>")
def stream(name):
    if name not in CACHE or not CACHE[name]:
        fetch_playlist_videos(name, PLAYLISTS[name])
        if name not in CACHE or not CACHE[name]:
            abort(404, "No videos found")

    vid = CACHE[name][0]
    CACHE[name].rotate(-1)

    url = f"https://www.youtube.com/watch?v={vid}"
    logging.info(f"[{name}] Streaming {url}")

    ffmpeg_cmd = [
        "ffmpeg", "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-i", url, "-f", "mp3", "-b:a", "128k", "-content_type", "audio/mpeg", "pipe:1"
    ]

    process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def generate():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            process.kill()

    return Response(generate(), mimetype="audio/mpeg")

# -----------------------------
# HTML TEMPLATES
# -----------------------------
HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Radio</title>
<style>
body { background:#000; color:#0f0; text-align:center; font-family:sans-serif; }
a { color:#0f0; text-decoration:none; }
button { background:#0f0; color:#000; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; }
input { padding:8px; width:90%; border-radius:8px; border:none; margin-bottom:10px; }
.playlist-btn { display:inline-block; border:2px solid #0f0; border-radius:12px; padding:10px 20px; margin:8px; }
.icon { margin-left:8px; font-size:18px; }
</style>
</head>
<body>
<h2>🎧 <span style="color:#0f0;">YouTube Mp3</span></h2>

{% for name in playlists %}
  <div>
    <a class="playlist-btn" href="/listen/{{name}}">▶️ {{name|capitalize}} Radio</a>
    <a class="icon" href="/shuffle/{{name}}" style="color:#ffa500;">🔀</a>
    <a class="icon" href="/delete/{{name}}" style="color:red;">🗑️</a>
  </div>
{% endfor %}

<h3 style="margin-top:20px;">Add New Playlist</h3>
<form action="/add_playlist" method="post">
  <input name="name" placeholder="Enter playlist name (e.g. Malayalam)">
  <br>
  <input name="url" placeholder="https://youtube.com/playlist?list=PLs0evDzPiKwAyJDAbmMOg44iuNLPaI4nn">
  <br>
  <button type="submit">Add Playlist</button>
</form>

</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name|capitalize}} Radio</title>
<style>
body { background:#000; color:#0f0; text-align:center; font-family:sans-serif; }
a { color:#0f0; text-decoration:none; }
audio { width:90%; margin:20px auto; display:block; }
</style>
</head>
<body>
<h3>🎶 {{name|capitalize}} Radio</h3>

<audio controls autoplay>
  <source src="/stream/{{name}}" type="audio/mpeg">
  Your browser does not support audio playback.
</audio>

<p style="margin-top:20px; font-size:18px;">
  🔗 Stream URL:<br>
  <a href="/stream/{{name}}" style="color:#0f0;">{{ request.host_url }}stream/{{name }}</a>
</p>

</body>
</html>
"""

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)