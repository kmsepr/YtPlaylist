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

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)

app = Flask(__name__)

COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
PLAYLISTS_FILE = "/mnt/data/playlists.json"
MAX_QUEUE_SIZE = 100  # chunks

# -----------------------------
# 🔄 AUTO UPDATE YT-DLP
# -----------------------------
def update_ytdlp():
    try:
        logging.info("🔄 Checking for yt-dlp update...")
        subprocess.run(["pip", "install", "-U", "yt-dlp"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logging.info("✅ yt-dlp updated successfully.")
    except Exception as e:
        logging.error(f"⚠️ Failed to update yt-dlp: {e}")

def periodic_ytdlp_update():
    while True:
        time.sleep(6 * 3600)  # every 6 hours
        update_ytdlp()

update_ytdlp()
threading.Thread(target=periodic_ytdlp_update, daemon=True).start()

# -----------------------------
# LOAD & SAVE PLAYLIST DATA
# -----------------------------
def load_playlists():
    if os.path.exists(PLAYLISTS_FILE):
        try:
            with open(PLAYLISTS_FILE, "r") as f:
                data = json.load(f)
                playlists = data.get("playlists", {})
                shuffle = set(data.get("shuffle", []))
                reverse = set(data.get("reverse", []))
                if playlists:
                    return playlists, shuffle, reverse
        except Exception as e:
            logging.error(f"Failed to load playlists: {e}")

    # default playlists
    defaults = {
        "Malayalam": "https://youtube.com/playlist?list=PLs0evDzPiKwAyJDAbmMOg44iuNLPaI4nn",
        "Hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
    }
    return defaults, {"Malayalam", "Hindi"}, set()

def save_playlists():
    try:
        with open(PLAYLISTS_FILE, "w") as f:
            json.dump(
                {"playlists": PLAYLISTS, "shuffle": list(SHUFFLE_PLAYLISTS), "reverse": list(REVERSE_PLAYLISTS)},
                f,
                indent=2
            )
    except Exception as e:
        logging.error(f"Failed to save playlists: {e}")

PLAYLISTS, SHUFFLE_PLAYLISTS, REVERSE_PLAYLISTS = load_playlists()
STREAMS = {}

# -----------------------------
# HTML
# -----------------------------
HOME_HTML = """..."""  # Keep as is
PLAYER_HTML = """..."""  # Keep as is

# -----------------------------
# CACHE
# -----------------------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load cache: {e}")
    return {}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")

CACHE = load_cache()

# -----------------------------
# LOAD PLAYLIST VIDEO IDS
# -----------------------------
def load_playlist_ids(name, force=False):
    now = time.time()
    cached = CACHE.get(name, {})
    if not force and cached and now - cached.get("time", 0) < 1800:
        return cached.get("ids", [])

    url = PLAYLISTS.get(name)
    if not url:
        return cached.get("ids", [])

    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        entries = data.get("entries", [])
        video_ids = [e["id"] for e in entries if e.get("id")]
        if not video_ids:
            logging.warning(f"[{name}] Playlist empty or failed to fetch.")
            return cached.get("ids", [])

        if name in REVERSE_PLAYLISTS:
            video_ids.reverse()
        if name in SHUFFLE_PLAYLISTS:
            random.shuffle(video_ids)

        CACHE[name] = {"ids": video_ids, "time": now}
        save_cache(CACHE)
        return video_ids
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("ids", [])

# -----------------------------
# STREAM WORKER
# -----------------------------
def stream_worker(name):
    stream = STREAMS[name]
    failed_videos = set()
    played_videos = set()
    shuffle_enabled = name in SHUFFLE_PLAYLISTS

    while True:
        try:
            if not stream["VIDEO_IDS"]:
                stream["VIDEO_IDS"] = load_playlist_ids(name, force=True)
                failed_videos.clear()
                played_videos.clear()
                if not stream["VIDEO_IDS"]:
                    time.sleep(10)
                    continue

            if shuffle_enabled:
                available = [v for v in stream["VIDEO_IDS"] if v not in failed_videos and v not in played_videos]
                if not available:
                    played_videos.clear()
                    available = [v for v in stream["VIDEO_IDS"] if v not in failed_videos]
                if not available:
                    time.sleep(15)
                    continue
                vid = random.choice(available)
                played_videos.add(vid)
            else:
                vid = stream["VIDEO_IDS"][stream["INDEX"] % len(stream["VIDEO_IDS"])]
                stream["INDEX"] += 1

            url = f"https://www.youtube.com/watch?v={vid}"
            result = subprocess.run(
                ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "--cookies", COOKIES_PATH, "-g", url],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
            )
            audio_url = result.stdout.strip()
            if not audio_url:
                failed_videos.add(vid)
                continue

            cmd = f'ffmpeg -re -i "{audio_url}" -b:a 40k -ac 1 -f mp3 pipe:1 -loglevel quiet'
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(stream["QUEUE"]) < MAX_QUEUE_SIZE:
                    stream["QUEUE"].append(chunk)

            proc.stdout.close()
            proc.stderr.close()
            proc.wait()

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}", exc_info=True)
            time.sleep(10)

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys(), shuffle_playlists=SHUFFLE_PLAYLISTS, reverse_playlists=REVERSE_PLAYLISTS)

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

@app.route("/add_playlist", methods=["POST"])
def add_playlist():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    if not name or not url:
        abort(400, "Name and URL required")

    import re
    match = re.search(r"(?:list=)([A-Za-z0-9_-]+)", url)
    if not match:
        abort(400, "Invalid YouTube playlist URL")
    url = f"https://www.youtube.com/playlist?list={match.group(1)}"

    PLAYLISTS[name] = url
    if request.form.get("shuffle"):
        SHUFFLE_PLAYLISTS.add(name)
    if request.form.get("reverse"):
        REVERSE_PLAYLISTS.add(name)
    save_playlists()

    video_ids = load_playlist_ids(name)
    STREAMS[name] = {"VIDEO_IDS": video_ids, "INDEX": 0, "QUEUE": deque(), "LOCK": threading.Lock(), "LAST_REFRESH": time.time()}
    threading.Thread(target=stream_worker, args=(name,), daemon=True).start()

    return redirect(url_for("home"))

@app.route("/delete/<name>")
def delete_playlist(name):
    if name not in PLAYLISTS:
        abort(404)
    STREAMS.pop(name, None)
    PLAYLISTS.pop(name, None)
    SHUFFLE_PLAYLISTS.discard(name)
    REVERSE_PLAYLISTS.discard(name)
    CACHE.pop(name, None)
    save_cache(CACHE)
    save_playlists()
    return redirect(url_for("home"))

# -----------------------------
# START STREAM WORKERS
# -----------------------------
def start_workers():
    for name in PLAYLISTS:
        STREAMS[name] = {"VIDEO_IDS": load_playlist_ids(name), "INDEX": 0, "QUEUE": deque(), "LOCK": threading.Lock(), "LAST_REFRESH": time.time()}
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()
    logging.info("🎧 Multi-Playlist YouTube Radio started!")

# Call this on import so Gunicorn workers start streaming
start_workers()
