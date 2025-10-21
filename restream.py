import os
import time
import json
import threading
import logging
import subprocess
from collections import deque
from flask import Flask, Response, abort
from logging.handlers import RotatingFileHandler

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)

app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"

PLAYLISTS = {
    "Malayalam": "https://youtube.com/playlist?list=PLYKzjRvMAychqR_ysgXiHAywPUsVw0AzE",
    "Hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
}

STREAMS = {}  # { name: {VIDEOS, INDEX, QUEUE, LOCK, LAST_REFRESH} }

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
def load_playlist(name, force=False):
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < 1800:
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
        CACHE[name] = {"videos": videos, "time": now}
        save_cache(CACHE)
        logging.info(f"[{name}] Loaded {len(videos)} videos successfully")
        return videos
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("videos", [])

# -----------------------------
# PRELOAD AND STREAM
# -----------------------------
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

def stream_worker(name):
    stream = STREAMS[name]
    failed_videos = set()
    fail_count = 0

    while True:
        try:
            # Reload playlist if empty
            if not stream["VIDEOS"]:
                logging.info(f"[{name}] Playlist empty, loading...")
                stream["VIDEOS"] = load_playlist(name, force=True)
                stream["INDEX"] = 0
                failed_videos.clear()

            # Auto-refresh every 30 min
            if time.time() - stream["LAST_REFRESH"] > 1800:
                logging.info(f"[{name}] Auto-refreshing playlist...")
                stream["VIDEOS"] = load_playlist(name, force=True)
                stream["INDEX"] = 0
                failed_videos.clear()
                stream["LAST_REFRESH"] = time.time()

            # Pick next video, skip failed ones
            for _ in range(len(stream["VIDEOS"])):
                url = stream["VIDEOS"][stream["INDEX"] % len(stream["VIDEOS"])]
                stream["INDEX"] += 1
                if url not in failed_videos:
                    break
            else:
                # All failed, refresh next loop
                continue

            logging.info(f"[{name}] ▶️ Preloading: {url}")
            direct_url = get_direct_audio_url(url)
            if not direct_url:
                logging.warning(f"[{name}] Failed to resolve direct URL, skipping...")
                failed_videos.add(url)
                continue

            # Stream the audio
            cmd = ["ffmpeg", "-i", direct_url, "-f", "mp3", "-vn", "pipe:1"]
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                for chunk in iter(lambda: proc.stdout.read(4096), b""):
                    if chunk:
                        stream["QUEUE"].append(chunk)

            logging.info(f"[{name}] Track finished")
            fail_count = 0

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}", exc_info=True)
            time.sleep(5)

# -----------------------------
# STREAM ENDPOINT
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
    return "<h2>🎧 YouTube Continuous Radio</h2><p>Use /stream/<name> to listen.</p>"

# -----------------------------
# MAIN
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