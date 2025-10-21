import os
import time
import json
import threading
import logging
import subprocess
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context
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
MAX_QUEUE_SIZE = 100  # chunks

PLAYLISTS = {
    "Malayalam": "https://youtube.com/playlist?list=PLs0evDzPiKwAyJDAbmMOg44iuNLPaI4nn",
    "Hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",

"Firsts": "https://youtu.be/SuF1x3GrIEI?si=vKW1LFXmdX6IFf0A",
}

STREAMS = {}  # { name: {VIDEO_IDS, INDEX, QUEUE, LOCK, LAST_REFRESH} }

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
body { background:#000;color:#0f0;text-align:center;font-family:sans-serif; }
a { color:#0f0; display:block; padding:10px; border:1px solid #0f0;
    margin:10px; border-radius:10px; text-decoration:none; }
</style>
</head>
<body>
<h2>🎧 YouTube Mp3</h2>
{% for name in playlists %}
<a href="/listen/{{name}}">▶️ {{name|capitalize}} Radio</a>
{% endfor %}
</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{name|capitalize}} Radio</title>
</head>
<body style="background:#000;color:#0f0;text-align:center;font-family:sans-serif;">
<h3>🎶 {{name|capitalize}} Radio</h3>
<a href="/stream/{{name}}" style="color:#0f0;font-size:18px;">⬇️ Download MP3</a>
<p>YouTube Playlist</p>
</body>
</html>
"""

# -----------------------------
# CACHE FUNCTIONS
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
            json.dump(data, f)
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
        logging.info(f"[{name}] Using cached playlist IDs ({len(cached['ids'])} videos)")
        return cached["ids"]

    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist IDs...")
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        video_ids = [
            e["id"] for e in data.get("entries", [])
            if not e.get("private") and e.get("age_limit", 0) == 0
        ]
        CACHE[name] = {"ids": video_ids, "time": now}
        save_cache(CACHE)
        logging.info(f"[{name}] Loaded {len(video_ids)} video IDs successfully")
        return video_ids
    except Exception as e:
        logging.error(f"[{name}] Playlist load failed: {e}")
        return cached.get("ids", [])

# -----------------------------
# STREAM WORKER
# -----------------------------
# -----------------------------
# STREAM WORKER (with yt-dlp -g)
# -----------------------------
def stream_worker(name):
    stream = STREAMS[name]
    failed_videos = set()

    while True:
        try:
            # Reload playlist if empty
            if not stream["VIDEO_IDS"]:
                logging.info(f"[{name}] Playlist empty, loading...")
                stream["VIDEO_IDS"] = load_playlist_ids(name, force=True)
                stream["INDEX"] = 0
                failed_videos.clear()
                if not stream["VIDEO_IDS"]:
                    logging.warning(f"[{name}] Playlist still empty after refresh, retrying in 10s...")
                    time.sleep(10)
                    continue

            # Auto-refresh every 30 min
            if time.time() - stream["LAST_REFRESH"] > 1800:
                logging.info(f"[{name}] Auto-refreshing playlist IDs...")
                stream["VIDEO_IDS"] = load_playlist_ids(name, force=True)
                stream["INDEX"] = 0
                failed_videos.clear()
                stream["LAST_REFRESH"] = time.time()

            # Pick next video
            for _ in range(len(stream["VIDEO_IDS"])):
                vid = stream["VIDEO_IDS"][stream["INDEX"] % len(stream["VIDEO_IDS"])]
                stream["INDEX"] += 1
                if vid not in failed_videos:
                    break
            else:
                logging.warning(f"[{name}] All videos failed, retrying in 10s...")
                time.sleep(10)
                continue

            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ Streaming: {url}")

            if not os.path.exists(COOKIES_PATH) or os.path.getsize(COOKIES_PATH) == 0:
                logging.warning(f"[{name}] Cookies missing or empty, skipping video")
                failed_videos.add(vid)
                continue

            # Get direct audio URL via yt-dlp -g
            try:
                result = subprocess.run(
                    [
                        "yt-dlp",
                        "-f", "bestaudio[ext=m4a]/bestaudio",
                        "--cookies", COOKIES_PATH,
                        "-g", url
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                audio_url = result.stdout.strip()
            except subprocess.CalledProcessError as e:
                logging.warning(f"[{name}] yt-dlp -g failed, skipping video: {url}")
                failed_videos.add(vid)
                continue

            # Stream audio via ffmpeg
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
            time.sleep(5)

# -----------------------------
# FLASK ROUTES
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

    headers = {
        "Content-Type": "audio/mpeg",
        "Content-Disposition": f'attachment; filename="{name}.mp3"'
    }

    return Response(stream_with_context(generate()), headers=headers)

@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS:
        abort(404)
    return render_template_string(PLAYER_HTML, name=name)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {
            "VIDEO_IDS": load_playlist_ids(name),
            "INDEX": 0,
            "QUEUE": deque(),
            "LOCK": threading.Lock(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()

    logging.info("🎧 Multi-Playlist YouTube Radio started!")
    logging.info(f"Logs: {LOG_PATH}")
    app.run(host="0.0.0.0", port=5000)