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
from urllib.parse import urlparse, parse_qs

# -----------------------------
# CONFIG & LOGGING
# -----------------------------
LOG_PATH = "/mnt/data/radio.log"
PLAYLISTS_FILE = "/mnt/data/playlists.json"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"  # stores both per-name cache and backups by playlist id
MAX_QUEUE_SIZE = 100

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)

app = Flask(__name__)

# -----------------------------
# PLAYLIST MANAGEMENT
# -----------------------------
def load_playlists():
    if os.path.exists(PLAYLISTS_FILE):
        try:
            with open(PLAYLISTS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load playlists.json: {e}")
    # Default playlists
    playlists = {
        "Malayalam": {"url": "https://youtube.com/playlist?list=PLs0evDzPiKwAyJDAbmMOg44iuNLPaI4nn", "shuffle": False, "reverse": False},
        "Hindi": {"url": "https://youtube.com/playlist?list=PLH67Zm2MkA5744xytd3SUdLVeZ4zJ6htc", "shuffle": False, "reverse": False},
    }
    save_playlists(playlists)
    return playlists

def save_playlists(data):
    try:
        with open(PLAYLISTS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save playlists.json: {e}")

PLAYLISTS = load_playlists()

# -----------------------------
# HTML TEMPLATES
# -----------------------------
HOME_HTML = """..."""  # (unchanged for brevity)
PLAYER_HTML = """..."""  # (unchanged for brevity)

# -----------------------------
# CACHE HANDLING (with backups)
# -----------------------------
DEFAULT_CACHE = {"by_name": {}, "backups": {}}

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Failed to load cache: {e}")
    return DEFAULT_CACHE.copy()

def save_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save cache: {e}")

CACHE = load_cache()

def extract_playlist_id(url):
    try:
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        return q.get("list", [None])[0]
    except Exception:
        return None

# -----------------------------
# PLAYLIST LOADING (with backup)
# -----------------------------
def load_playlist_ids(name, force=False):
    info = PLAYLISTS[name]
    now = time.time()
    cached_entry = CACHE.get("by_name", {}).get(name, {})
    if not force and cached_entry and now - cached_entry.get("time", 0) < 1800:
        logging.info(f"[{name}] Using cached playlist IDs ({len(cached_entry.get('ids', []))})")
        return cached_entry.get("ids", [])

    url = info["url"].split("&")[0]  # remove &si etc.
    playlist_id = extract_playlist_id(url)
    cmd = ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH]

    try:
        logging.info(f"[{name}] Refreshing playlist IDs from YouTube...")
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode != 0:
            logging.error(f"[{name}] yt-dlp failed (exit {result.returncode}):\n{result.stderr.strip()}")
            raise subprocess.CalledProcessError(result.returncode, cmd)

        data = json.loads(result.stdout)
        ids = [e["id"] for e in data.get("entries", []) if e.get("id") and not e.get("private")]

        if info.get("reverse"):
            ids.reverse()
        if info.get("shuffle"):
            random.shuffle(ids)

        if ids:
            CACHE.setdefault("by_name", {})[name] = {"ids": ids, "time": now}
            save_cache(CACHE)
            logging.info(f"[{name}] ✅ Loaded {len(ids)} video IDs from YouTube.")

            if playlist_id:
                title = data.get("title") or name
                CACHE.setdefault("backups", {})[playlist_id] = {
                    "title": title,
                    "videos": ids.copy(),
                    "last_updated": now
                }
                save_cache(CACHE)
                logging.info(f"[{name}] Backup updated for playlist id {playlist_id} ({len(ids)} videos).")
        else:
            logging.warning(f"[{name}] Playlist loaded but no videos found.")

        return ids

    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        if cached_entry.get("ids"):
            logging.warning(f"[{name}] Using cached {len(cached_entry['ids'])} IDs.")
            return cached_entry["ids"]
        if playlist_id:
            backup = CACHE.get("backups", {}).get(playlist_id, {})
            if backup.get("videos"):
                vids = backup["videos"].copy()
                if info.get("reverse"):
                    vids.reverse()
                if info.get("shuffle"):
                    random.shuffle(vids)
                CACHE.setdefault("by_name", {})[name] = {"ids": vids, "time": now}
                save_cache(CACHE)
                return vids
        logging.warning(f"[{name}] No cached IDs available.")
        return []

# -----------------------------
# STREAM WORKER (fixed)
# -----------------------------
STREAMS = {}

def stream_worker(name):
    stream = STREAMS[name]
    failed = set()

    while True:
        try:
            if not stream["VIDEO_IDS"]:
                stream["VIDEO_IDS"] = load_playlist_ids(name, force=True)
                stream["INDEX"] = 0
                failed.clear()
                if not stream["VIDEO_IDS"]:
                    logging.warning(f"[{name}] Playlist empty, retrying in 10s...")
                    time.sleep(10)
                    continue

            if time.time() - stream["LAST_REFRESH"] > 1800:
                stream["VIDEO_IDS"] = load_playlist_ids(name, force=True)
                stream["INDEX"] = 0
                stream["LAST_REFRESH"] = time.time()

            vid = stream["VIDEO_IDS"][stream["INDEX"] % len(stream["VIDEO_IDS"])]
            stream["INDEX"] += 1
            if vid in failed:
                continue

            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ Streaming: {url}")

            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "-o", "-", url,
                "-q", "--no-warnings",
                "--geo-bypass",
                "--no-playlist",
            ]

            ffmpeg_cmd = [
                "ffmpeg", "-re", "-i", "pipe:0",
                "-vn", "-acodec", "libmp3lame",
                "-b:a", "64k", "-ar", "44100",
                "-f", "mp3", "pipe:1",
                "-loglevel", "error",
            ]

            yt_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=yt_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            yt_proc.stdout.close()

            stderr_buffer = []
            while True:
                chunk = ffmpeg_proc.stdout.read(4096)
                if not chunk:
                    break
                if len(stream["QUEUE"]) < MAX_QUEUE_SIZE:
                    stream["QUEUE"].append(chunk)

            err_output = ffmpeg_proc.stderr.read().decode(errors="ignore").strip()
            if err_output:
                stderr_buffer.append(err_output)

            yt_proc.wait()
            ffmpeg_proc.wait()

            if ffmpeg_proc.returncode != 0:
                logging.error(f"[{name}] ffmpeg exited with code {ffmpeg_proc.returncode}")
                if stderr_buffer:
                    logging.error(f"[{name}] STDERR:\n{''.join(stderr_buffer[-10:])}")
                failed.add(vid)
                continue

            if stderr_buffer:
                logging.info(f"[{name}] Info:\n{''.join(stderr_buffer[-10:])}")

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}", exc_info=True)
            time.sleep(5)

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/add", methods=["POST"])
def add_playlist():
    name = request.form["name"].strip()
    url = request.form["url"].strip().split("&")[0]
    shuffle = "shuffle" in request.form
    reverse = "reverse" in request.form

    if name in PLAYLISTS:
        return f"<p>Playlist '{name}' already exists.</p><a href='/'>Back</a>"

    PLAYLISTS[name] = {"url": url, "shuffle": shuffle, "reverse": reverse}
    save_playlists(PLAYLISTS)
    STREAMS[name] = {
        "VIDEO_IDS": load_playlist_ids(name, force=True),
        "INDEX": 0,
        "QUEUE": deque(),
        "LAST_REFRESH": time.time(),
    }
    threading.Thread(target=stream_worker, args=(name,), daemon=True).start()
    logging.info(f"[{name}] Added new playlist.")
    return redirect(url_for("home"))

@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS: abort(404)
    return render_template_string(PLAYER_HTML, name=name)

@app.route("/stream/<name>")
def stream_audio(name):
    if name not in STREAMS: abort(404)
    stream = STREAMS[name]
    def gen():
        while True:
            if stream["QUEUE"]:
                yield stream["QUEUE"].popleft()
            else:
                time.sleep(0.1)
    return Response(stream_with_context(gen()), mimetype="audio/mpeg")

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {
            "VIDEO_IDS": load_playlist_ids(name),
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()
    logging.info("🎧 Multi-Playlist YouTube Radio started!")
    logging.info(f"Logs: {LOG_PATH}")
    app.run(host="0.0.0.0", port=5000)