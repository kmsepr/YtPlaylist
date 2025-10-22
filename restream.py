import os
import time
import json
import threading
import logging
import subprocess
import random
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context, request, redirect, url_for
from logging.handlers import RotatingFileHandler

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=2)
logging.basicConfig(handlers=[handler], level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# -----------------------------
# APP INIT
# -----------------------------
app = Flask(__name__)

# -----------------------------
# STORAGE
# -----------------------------
PLAYLIST_FILE = "playlists.json"
PLAYLIST_CACHE = {}

if not os.path.exists(PLAYLIST_FILE):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump({}, f)

def load_playlists():
    with open(PLAYLIST_FILE, "r") as f:
        return json.load(f)

def save_playlists(data):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)

PLAYLISTS = load_playlists()

# -----------------------------
# BACKGROUND REFRESH THREAD
# -----------------------------
def refresh_playlist(name, url):
    logging.info(f"[{name}] Refreshing playlist IDs...")
    try:
        result = subprocess.run(
            ["yt-dlp", "-j", "--flat-playlist", url],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        ids = [json.loads(l)["id"] for l in lines if l.strip()]
        random.shuffle(ids)
        PLAYLIST_CACHE[name] = deque(ids)
        logging.info(f"[{name}] Loaded {len(ids)} video IDs successfully")
    except Exception as e:
        logging.error(f"[{name}] Failed to refresh playlist: {e}")

def refresh_all_playlists():
    while True:
        for name, data in PLAYLISTS.items():
            refresh_playlist(name, data["url"])
        time.sleep(3600)

threading.Thread(target=refresh_all_playlists, daemon=True).start()

# -----------------------------
# STREAMING
# -----------------------------
def generate_stream(video_id):
    ytdl_cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", "-",
        f"https://www.youtube.com/watch?v={video_id}"
    ]
    ffmpeg_cmd = [
        "ffmpeg",
        "-i", "pipe:0",
        "-f", "mp3",
        "-b:a", "128k",
        "pipe:1"
    ]
    ytdl_proc = subprocess.Popen(ytdl_cmd, stdout=subprocess.PIPE)
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=ytdl_proc.stdout, stdout=subprocess.PIPE)

    ytdl_proc.stdout.close()
    try:
        for chunk in iter(lambda: ffmpeg_proc.stdout.read(4096), b""):
            yield chunk
    finally:
        ytdl_proc.kill()
        ffmpeg_proc.kill()

@app.route("/stream/<name>")
def stream_playlist(name):
    if name not in PLAYLIST_CACHE or not PLAYLIST_CACHE[name]:
        if name in PLAYLISTS:
            refresh_playlist(name, PLAYLISTS[name]["url"])
        else:
            abort(404, "Playlist not found")

    ids = PLAYLIST_CACHE.get(name, deque())
    if not ids:
        abort(404, "No videos found in playlist")

    video_id = ids[0]
    ids.rotate(-1)

    logging.info(f"[{name}] ▶️ Streaming: https://www.youtube.com/watch?v={video_id}")
    return Response(
        stream_with_context(generate_stream(video_id)),
        mimetype="audio/mpeg"
    )

# -----------------------------
# ROUTES
# -----------------------------
HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Radio</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; text-align: center; background: #111; color: #eee; margin: 0; }
        h1 { background: #222; padding: 10px; }
        .playlist { background: #222; margin: 10px auto; padding: 10px; border-radius: 8px; width: 90%; max-width: 400px; }
        form { margin: 20px auto; background: #222; padding: 15px; border-radius: 10px; width: 90%; max-width: 400px; }
        input[type=text], input[type=url] {
            width: 90%; padding: 10px; margin: 5px 0; border: none; border-radius: 6px; font-size: 1em;
        }
        button { padding: 8px 15px; border: none; border-radius: 6px; background: #28a745; color: white; cursor: pointer; margin-top: 10px; }
        button:hover { background: #218838; }
        .delete { background: #c0392b; }
        .delete:hover { background: #e74c3c; }
        audio { width: 90%; margin-top: 10px; }
        small { color: #aaa; }
    </style>
</head>
<body>
    <h1>🎧 YouTube Radio</h1>

    <h3>Add New Playlist</h3>
    <form method="POST" action="/add_playlist">
        <input type="text" name="name" placeholder="Playlist Name (e.g. Malayalam Radio)" required>
        <input type="url" name="url" placeholder="Paste YouTube Playlist URL" required>
        <small>Example: https://www.youtube.com/playlist?list=PLn3BMOY0H7UtVBWbP963mAYdmbRD8YbCi</small><br>
        <label><input type="checkbox" name="shuffle"> Shuffle</label><br>
        <button type="submit">➕ Add Playlist</button>
    </form>

    <h3>Available Playlists</h3>
    {% for name, data in playlists.items() %}
        <div class="playlist">
            <strong>{{ name }}</strong><br>
            <a href="{{ url_for('stream_playlist', name=name) }}" target="_blank">
                <button>▶️ Play</button>
            </a>
            <a href="{{ url_for('delete_playlist', name=name) }}">
                <button class="delete">🗑️ Delete</button>
            </a>
            <br>
            <small><a href="{{ data.url }}" target="_blank" style="color:#aaa;">{{ data.url }}</a></small>
        </div>
    {% endfor %}
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/add_playlist", methods=["POST"])
def add_playlist():
    name = request.form["name"].strip()
    url = request.form["url"].strip()
    shuffle = "shuffle" in request.form

    if not name or not url:
        return "Missing fields", 400

    PLAYLISTS[name] = {"url": url, "shuffle": shuffle}
    save_playlists(PLAYLISTS)
    refresh_playlist(name, url)
    return redirect(url_for("home"))

@app.route("/delete/<name>")
def delete_playlist(name):
    if name in PLAYLISTS:
        PLAYLISTS.pop(name)
        save_playlists(PLAYLISTS)
        PLAYLIST_CACHE.pop(name, None)
    return redirect(url_for("home"))

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)