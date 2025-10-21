import os
import json
import time
import logging
import threading
import subprocess
from flask import Flask, redirect, abort

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"

PLAYLISTS = {
    "Malayalam": "https://youtube.com/playlist?list=PLYKzjRvMAychqR_ysgXiHAywPUsVw0AzE",
    "Hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
}

# -----------------------------
# Cache & Playlist Management
# -----------------------------
CACHE = {}
CURRENT_INDEX = {}
LAST_REFRESH = {}

def load_cache():
    global CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                CACHE = json.load(f)
        except:
            CACHE = {}

def save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(CACHE, f)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")

def load_playlist(name, force=False):
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < 1800:
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
        save_cache()
        logging.info(f"[{name}] Playlist loaded: {len(videos)} videos")
        return videos
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("videos", [])

def get_next_video(name):
    videos = load_playlist(name)
    if not videos:
        return None
    idx = CURRENT_INDEX.get(name, 0) % len(videos)
    CURRENT_INDEX[name] = idx + 1
    return videos[idx]

def get_direct_audio_url(video_url):
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-g", video_url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logging.warning(f"Failed to get direct URL: {video_url} -> {e}")
        return None

# -----------------------------
# Stream Route
# -----------------------------
@app.route("/stream/<name>")
def stream_playlist(name):
    if name not in PLAYLISTS:
        abort(404)
    
    video = get_next_video(name)
    if not video:
        abort(500, description="No videos available")

    direct_url = get_direct_audio_url(video)
    if not direct_url:
        abort(500, description="Failed to resolve video URL")

    return redirect(direct_url)

# -----------------------------
# Home
# -----------------------------
@app.route("/")
def home():
    links = "".join([f'<a href="/stream/{n}">▶️ {n}</a><br>' for n in PLAYLISTS])
    return f"<h2>YouTube Playlist Stream</h2>{links}"

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    load_cache()
    for name in PLAYLISTS:
        CURRENT_INDEX[name] = 0
        LAST_REFRESH[name] = time.time()
    logging.info("🎧 Playlist streaming server started!")
    app.run(host="0.0.0.0", port=5000)