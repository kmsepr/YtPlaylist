import os
import json
import time
import logging
import subprocess
from flask import Flask, Response, abort, render_template_string

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"

PLAYLISTS = {
    "Malayalam": "https://youtube.com/playlist?list=PLYKzjRvMAychqR_ysgXiHAywPUsVw0AzE",
    "Hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
}

# -----------------------------
# CACHE
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
# LOAD PLAYLIST
# -----------------------------
def load_playlist(name):
    cached = CACHE.get(name, {})
    if cached and time.time() - cached.get("time", 0) < 1800:
        logging.info(f"[{name}] Using cached playlist ({len(cached['videos'])} videos)")
        return cached["videos"]

    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist...")
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        videos = [f"https://www.youtube.com/watch?v={e['id']}" for e in data.get("entries", [])]
        CACHE[name] = {"videos": videos, "time": time.time()}
        save_cache(CACHE)
        logging.info(f"[{name}] Loaded {len(videos)} videos successfully")
        return videos
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("videos", [])

# -----------------------------
# STREAM/DOWNLOAD ON DEMAND
# -----------------------------
def get_direct_audio_url(video_url):
    """Resolve direct audio URL using yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-g", video_url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logging.warning(f"Failed to get direct URL: {video_url} -> {e}")
        return None

@app.route("/stream/<name>/<int:index>")
def stream_audio(name, index):
    if name not in PLAYLISTS:
        abort(404)

    videos = load_playlist(name)
    if index < 0 or index >= len(videos):
        abort(404)

    url = videos[index]
    logging.info(f"[{name}] Streaming on-demand: {url}")

    direct_url = get_direct_audio_url(url)
    if not direct_url:
        abort(500, description="Failed to resolve video")

    # Use FFmpeg to stream as MP3
    cmd = ["ffmpeg", "-i", direct_url, "-f", "mp3", "-vn", "pipe:1"]

    def generate():
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            for chunk in iter(lambda: proc.stdout.read(4096), b""):
                if chunk:
                    yield chunk

    return Response(generate(), content_type="audio/mpeg")

# -----------------------------
# SIMPLE HOME
# -----------------------------
HOME_HTML = """
<!DOCTYPE html>
<html>
<head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Downloader</title>
<style>
body { background:#000;color:#0f0;text-align:center;font-family:sans-serif; }
a { color:#0f0; display:block; padding:10px; border:1px solid #0f0;
    margin:10px; border-radius:10px; text-decoration:none; }
</style>
</head>
<body>
<h2>🎧 YouTube Download</h2>
{% for name, videos in playlists.items() %}
<h3>{{name}}</h3>
{% for idx, vid in enumerate(videos) %}
<a href="/stream/{{name}}/{{idx}}">▶️ Download Track {{idx+1}}</a>
{% endfor %}
{% endfor %}
</body>
</html>
"""

@app.route("/")
def home():
    playlists = {name: load_playlist(name) for name in PLAYLISTS}
    return render_template_string(HOME_HTML, playlists=playlists)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    logging.info("🎧 YouTube Downloader Server started!")
    app.run(host="0.0.0.0", port=5000)