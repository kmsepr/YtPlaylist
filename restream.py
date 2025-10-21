import os
import time
import threading
import logging
import subprocess
import json
from flask import Flask, Response, render_template_string, request, redirect

# -----------------------
# CONFIG
# -----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
PLAYLISTS_FILE = "playlists.json"
PLAYLISTS = {}
LOCK = threading.Lock()

# -----------------------
# HTML UI
# -----------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Restream</title>
<style>
body { font-family: sans-serif; text-align: center; background: #000; color: #0f0; margin: 0; padding: 1em; }
input, button { padding: 8px; margin: 5px; border-radius: 6px; border: none; }
button { background: #0f0; color: #000; font-weight: bold; }
a { color: #0f0; text-decoration: none; display: block; margin: 5px; }
</style>
</head>
<body>
<h2>🎧 YouTube Restream</h2>
<form method="POST" action="/add">
  <input name="name" placeholder="playlist name" required>
  <input name="url" placeholder="YouTube playlist URL" required size="40">
  <button type="submit">➕ Add</button>
</form>
<h3>Available Streams</h3>
{% for name in playlists %}
  <a href="/playlist/{{ name | urlencode }}.mp3" target="_blank">{{ name }}</a>
{% endfor %}
</body>
</html>
"""

# -----------------------
# LOAD/SAVE PLAYLISTS
# -----------------------
def load_playlists():
    global PLAYLISTS
    if os.path.exists(PLAYLISTS_FILE):
        with open(PLAYLISTS_FILE, "r") as f:
            PLAYLISTS = json.load(f)
    else:
        PLAYLISTS = {}

def save_playlists():
    with LOCK:
        with open(PLAYLISTS_FILE, "w") as f:
            json.dump(PLAYLISTS, f, indent=2)

# -----------------------
# PLAYLIST PARSER
# -----------------------
def get_videos_from_playlist(url):
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        videos = []
        for e in data.get("entries", []):
            vid = e.get("id")
            if vid and not vid.startswith("http"):
                videos.append(f"https://www.youtube.com/watch?v={vid}")
            elif vid and vid.startswith("http"):
                videos.append(vid)
        return videos
    except Exception as e:
        logging.error(f"Failed to load playlist {url}: {e}")
        return []

# -----------------------
# STREAM GENERATOR
# -----------------------
def stream_playlist(url):
    videos = get_videos_from_playlist(url)
    if not videos:
        yield b""
        return
    index = 0
    while True:
        video = videos[index % len(videos)]
        index += 1
        logging.info(f"🎧 Streaming: {video}")
        process = subprocess.Popen(
            ["yt-dlp", "-f", "bestaudio", "-o", "-", video, "--cookies", COOKIES_PATH, "--quiet"],
            stdout=subprocess.PIPE
        )
        for chunk in iter(lambda: process.stdout.read(1024), b""):
            yield chunk
        process.kill()

# -----------------------
# ROUTES
# -----------------------
@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE, playlists=list(PLAYLISTS.keys()))

@app.route("/add", methods=["POST"])
def add_playlist():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    if not name or not url:
        return redirect("/")
    PLAYLISTS[name] = url
    save_playlists()
    logging.info(f"✅ Added playlist '{name}' -> {url}")
    return redirect("/")

@app.route("/playlist/<path:name>.mp3")
def playlist_stream(name):
    name = name.replace("%20", " ")
    url = PLAYLISTS.get(name)
    if not url:
        logging.warning(f"❌ Playlist '{name}' not found")
        return "Playlist not found", 404
    logging.info(f"▶️ Starting stream for '{name}' ({url})")
    return Response(stream_playlist(url), content_type="audio/mpeg")

# -----------------------
# MAIN
# -----------------------
if __name__ == "__main__":
    load_playlists()
    app.run(host="0.0.0.0", port=5000)