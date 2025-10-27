import os
import time
import json
import logging
import threading
from flask import Flask, Response, render_template_string, request
import yt_dlp

# -----------------------
# CONFIG
# -----------------------
app = Flask(__name__)

CACHE_DIR = "/mnt/data/radio_cache"
CACHE_FILE = os.path.join(CACHE_DIR, "cache.json")

os.makedirs(CACHE_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 🎧 You can add more playlists here easily
PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    # "malayalam_hits": "https://youtube.com/playlist?list=XXXXXX",
    # "islamic_radio": "https://youtube.com/playlist?list=YYYYYY",
}

CACHE = {}   # {playlist_name: {path, url, timestamp}}
QUEUES = {}  # {playlist_name: [video_urls]}
NEXTS = {}   # {playlist_name: next_url}


# -----------------------
# UTILITIES
# -----------------------

def load_cache():
    global CACHE
    if os.path.exists(CACHE_FILE):
        try:
            CACHE = json.load(open(CACHE_FILE))
        except Exception:
            CACHE = {}
    else:
        CACHE = {}


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(CACHE, f)


def refresh_playlist(name):
    """Fetch YouTube playlist URLs for a given playlist name."""
    global QUEUES
    url = PLAYLISTS[name]
    logging.info(f"[{name}] Refreshing playlist...")
    ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = info.get("entries", [])
            QUEUES[name] = ["https://www.youtube.com/watch?v=" + e["url"] for e in entries if e.get("url")]
        logging.info(f"[{name}] Cached {len(QUEUES[name])} videos.")
    except Exception as e:
        logging.error(f"[{name}] Failed to refresh playlist: {e}")
        QUEUES[name] = []


def download_track(name, url, filename):
    """Download a single YouTube track."""
    logging.info(f"[{name}] ⬇️ Downloading: {url}")
    try:
        output_path = os.path.join(CACHE_DIR, filename)
        if os.path.exists(output_path):
            os.remove(output_path)
        ydl_opts = {"format": "140", "outtmpl": output_path, "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        CACHE[name] = {"path": output_path, "timestamp": time.time(), "url": url}
        save_cache()
        logging.info(f"[{name}] ✅ Download complete and cached.")
        return output_path
    except Exception as e:
        logging.error(f"[{name}] Download failed: {e}")
        return None


def predownload_next(name):
    """Pre-download the next track for a specific playlist."""
    global NEXTS
    queue = QUEUES.get(name, [])
    if queue:
        NEXTS[name] = queue.pop(0)
        logging.info(f"[{name}] Pre-downloading next: {NEXTS[name]}")
        download_track(name, NEXTS[name], f"{name}_next.m4a")
    else:
        logging.info(f"[{name}] No next track available yet.")


# -----------------------
# STREAMING
# -----------------------

@app.route("/")
def home():
    return render_template_string("""
    <html>
    <head>
        <title>YouTube Radio</title>
        <style>
            body { background:#000; color:#0f0; font-family:monospace; text-align:center; }
            a { color:#0f0; text-decoration:none; display:block; margin:10px; }
        </style>
    </head>
    <body>
        <h2>🎶 YouTube Radio</h2>
        {% for name in playlists %}
            <a href="/station/{{name}}">▶️ {{name}}</a>
        {% endfor %}
    </body>
    </html>
    """, playlists=PLAYLISTS.keys())


@app.route("/station/<name>")
def station(name):
    if name not in PLAYLISTS:
        return "Invalid station", 404
    current_url = CACHE.get(name, {}).get("url", "None")
    return render_template_string("""
    <html>
    <head>
        <title>🎧 {{name}}</title>
        <style>
            body { background:#000; color:#0f0; font-family:monospace; text-align:center; }
        </style>
    </head>
    <body>
        <h2>🎶 YouTube Radio - {{name}}</h2>
        <audio controls autoplay onended="location.href='/next/{{name}}'">
            <source src="/stream/{{name}}" type="audio/mpeg">
        </audio>
        <p>Now playing: {{ current }}</p>
    </body>
    </html>
    """, name=name, current=current_url)


@app.route("/stream/<name>")
def stream(name):
    if name not in PLAYLISTS:
        return "Unknown station", 404
    cache_entry = CACHE.get(name)
    if not cache_entry or not os.path.exists(cache_entry.get("path", "")):
        return "Stream not ready yet, please wait...", 503

    def generate():
        with open(cache_entry["path"], "rb") as f:
            chunk = f.read(4096)
            while chunk:
                yield chunk
                chunk = f.read(4096)

    # Start pre-downloading next track
    threading.Thread(target=predownload_next, args=(name,), daemon=True).start()

    response = Response(generate(), mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "public, max-age=3600"  # valid 1 hour
    return response


@app.route("/next/<name>")
def next_track(name):
    global NEXTS
    if name not in PLAYLISTS:
        return "Invalid station", 404

    next_url = NEXTS.get(name)
    next_path = os.path.join(CACHE_DIR, f"{name}_next.m4a")

    if not next_url or not os.path.exists(next_path):
        return "Next track not ready yet.", 503

    CACHE[name] = {"path": next_path, "timestamp": time.time(), "url": next_url}
    save_cache()
    NEXTS[name] = None

    # Begin next prefetch
    threading.Thread(target=predownload_next, args=(name,), daemon=True).start()

    return render_template_string("""
    <html>
    <head><meta http-equiv="refresh" content="1;url=/station/{{name}}" /></head>
    <body style="background:#000;color:#0f0;text-align:center;">
        <p>⏭️ Loading next track...</p>
    </body>
    </html>
    """, name=name)


# -----------------------
# BACKGROUND REFRESH
# -----------------------

def background_worker():
    """Refresh all playlists hourly."""
    while True:
        for name in PLAYLISTS:
            try:
                refresh_playlist(name)
            except Exception as e:
                logging.error(f"[{name}] Error refreshing playlist: {e}")
        time.sleep(3600)


# -----------------------
# MAIN ENTRY
# -----------------------

if __name__ == "__main__":
    load_cache()

    # Initialize all playlists
    for name in PLAYLISTS:
        refresh_playlist(name)
        if name not in CACHE:
            queue = QUEUES.get(name, [])
            if queue:
                first = queue.pop(0)
                download_track(name, first, f"{name}.m4a")
                threading.Thread(target=predownload_next, args=(name,), daemon=True).start()

    threading.Thread(target=background_worker, daemon=True).start()

    logging.info("🚀 YouTube Radio started successfully!")
    logging.info("🌐 Open http://0.0.0.0:8000 to access the UI.")
    app.run(host="0.0.0.0", port=8000, debug=False)