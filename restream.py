import os
import json
import random
import subprocess
import threading
import time
import logging
from flask import Flask, Response, request, redirect, render_template_string, abort

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

COOKIES = "/mnt/data/cookies.txt"
PLAYLISTS_FILE = "playlists.json"
LOCK = threading.Lock()

# -----------------------------
# Load saved playlists
# -----------------------------
if os.path.exists(PLAYLISTS_FILE):
    with open(PLAYLISTS_FILE, "r") as f:
        PLAYLISTS = json.load(f)
else:
    PLAYLISTS = {}

# -----------------------------
# HTML Home
# -----------------------------
HTML_HOME = """
<!doctype html>
<title>YouTube Playlist Radio</title>
<h2>🎧 YouTube Playlist Radio</h2>
<form action="/add" method="post">
  <input type="text" name="name" placeholder="Name" required>
  <input type="url" name="url" placeholder="Playlist URL" required>
  <button type="submit">Add Playlist</button>
</form>

<h3>Available Streams</h3>
<ul>
{% for name in playlists %}
  <li><b>{{ name }}</b> — <a href="/playlist/{{ name }}.mp3" target="_blank">🎵 Play Stream</a></li>
{% endfor %}
</ul>
"""

# -----------------------------
# Add Playlist
# -----------------------------
@app.route("/add", methods=["POST"])
def add_playlist():
    name = request.form.get("name").strip()
    url = request.form.get("url").strip()

    if not name or not url:
        abort(400, "Missing name or URL")

    with LOCK:
        PLAYLISTS[name] = url
        with open(PLAYLISTS_FILE, "w") as f:
            json.dump(PLAYLISTS, f, indent=2)

    logging.info(f"✅ Added playlist '{name}' -> {url}")
    return redirect("/")

# -----------------------------
# Home Page
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HTML_HOME, playlists=PLAYLISTS)

# -----------------------------
# Get playlist videos
# -----------------------------
def get_videos(playlist_url):
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        "--cookies", COOKIES, playlist_url
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    videos = []
    for line in proc.stdout:
        try:
            data = json.loads(line.strip())
            if "url" in data:
                videos.append(f"https://www.youtube.com/watch?v={data['url']}")
        except Exception:
            pass
    proc.wait()
    return videos

# -----------------------------
# Stream generator
# -----------------------------
def stream_playlist(url):
    videos = get_videos(url)
    if not videos:
        logging.error("No videos found.")
        return

    while True:
        video = random.choice(videos)
        logging.info(f"🎧 Streaming: {video}")

        ytdlp_cmd = [
            "yt-dlp", "-f", "bestaudio", "-o", "-", "--cookies", COOKIES,
            "--quiet", "--no-warnings", video
        ]
        ffmpeg_cmd = [
            "ffmpeg", "-loglevel", "quiet", "-i", "pipe:0",
            "-f", "mp3", "-b:a", "128k", "pipe:1"
        ]

        try:
            ytdlp = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
            ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp.stdout, stdout=subprocess.PIPE)

            while True:
                chunk = ffmpeg.stdout.read(1024)
                if not chunk:
                    break
                yield chunk

            ffmpeg.wait()
            ytdlp.terminate()
        except Exception as e:
            logging.error(f"Error streaming: {e}")
            time.sleep(5)

# -----------------------------
# Stream route
# -----------------------------
@app.route("/playlist/<name>.mp3")
def stream(name):
    if name not in PLAYLISTS:
        abort(404, f"Playlist '{name}' not found")
    playlist_url = PLAYLISTS[name]
    logging.info(f"▶️ Starting stream for '{name}' ({playlist_url})")
    return Response(stream_playlist(playlist_url), mimetype="audio/mpeg")

# -----------------------------
# Run server
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)