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

YOUTUBE_PLAYLIST = "https://www.youtube.com/playlist?list=PLt7epkU1Cq1sQBuJqJr8bTJKFoD2DhU-f"  # example
CACHE = {}
QUEUE = []
CURRENT = None
NEXT = None


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


def refresh_playlist():
    """Fetch YouTube playlist URLs."""
    global QUEUE
    logging.info("[kas_ranker] Refreshing playlist...")
    ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(YOUTUBE_PLAYLIST, download=False)
            entries = info.get("entries", [])
            QUEUE = ["https://www.youtube.com/watch?v=" + e["url"] for e in entries if e.get("url")]
        logging.info(f"[kas_ranker] Cached {len(QUEUE)} videos (latest first).")
    except Exception as e:
        logging.error(f"Failed to refresh playlist: {e}")


def download_track(url, filename="kas_ranker.m4a"):
    """Download one YouTube track and cache path."""
    logging.info(f"[kas_ranker] ⬇️ Downloading: {url}")
    try:
        output_path = os.path.join(CACHE_DIR, filename)
        ydl_opts = {
            "format": "140",
            "outtmpl": output_path,
            "quiet": True,
        }
        if os.path.exists(output_path):
            os.remove(output_path)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        CACHE["kas_ranker"] = {
            "path": output_path,
            "timestamp": time.time(),
            "url": url,
        }
        save_cache()
        logging.info("[kas_ranker] ✅ Download complete and cached.")
        return output_path
    except Exception as e:
        logging.error(f"[kas_ranker] Download failed: {e}")
        return None


def predownload_next():
    """Start pre-downloading next track while current is playing."""
    global NEXT
    if QUEUE:
        NEXT = QUEUE.pop(0)
        logging.info(f"[kas_ranker] Pre-downloading next: {NEXT}")
        download_track(NEXT, filename="next_track.m4a")
    else:
        logging.info("[kas_ranker] No next track available yet.")


# -----------------------
# STREAMING
# -----------------------

@app.route("/")
def index():
    current_url = CACHE.get("kas_ranker", {}).get("url", "None")
    return render_template_string("""
    <html>
    <head>
        <title>🎧 YouTube Radio</title>
        <style>
            body { background: #000; color: #0f0; font-family: monospace; text-align: center; }
            a, button { color: #0f0; text-decoration: none; border: none; background: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <h2>🎶 YouTube Radio - kas_ranker</h2>
        <audio controls autoplay onended="location.href='/next'">
            <source src="/stream/kas_ranker" type="audio/mpeg">
        </audio>
        <p>Now playing: {{ current }}</p>
    </body>
    </html>
    """, current=current_url)


@app.route("/stream/<station>")
def stream(station):
    cache_entry = CACHE.get(station)
    if not cache_entry or "path" not in cache_entry:
        return "Stream not ready yet, please wait a few seconds...", 503

    path = cache_entry.get("path")
    if not path or not os.path.exists(path):
        return "Cached audio file not found", 404

    def generate():
        with open(path, "rb") as f:
            chunk = f.read(4096)
            while chunk:
                yield chunk
                chunk = f.read(4096)

    # Begin downloading next track while streaming current
    threading.Thread(target=predownload_next, daemon=True).start()

    response = Response(generate(), mimetype="audio/mpeg")
    response.headers["Cache-Control"] = "public, max-age=3600"  # valid 1 hour
    return response


@app.route("/next")
def play_next():
    """Switch to next track after current ends."""
    global NEXT
    if not NEXT:
        return "No next track ready.", 503

    next_path = os.path.join(CACHE_DIR, "next_track.m4a")
    if not os.path.exists(next_path):
        return "Next track not downloaded yet.", 503

    # Replace current with next
    CACHE["kas_ranker"] = {
        "path": next_path,
        "timestamp": time.time(),
        "url": NEXT,
    }
    save_cache()
    NEXT = None

    # Start pre-downloading the next after switching
    threading.Thread(target=predownload_next, daemon=True).start()

    return render_template_string("""
    <html>
    <head><meta http-equiv="refresh" content="1;url=/" /></head>
    <body style="background:#000;color:#0f0;text-align:center;">
        <p>⏭️ Loading next track...</p>
    </body>
    </html>
    """)


# -----------------------
# BACKGROUND THREADS
# -----------------------

def background_worker():
    """Periodic playlist refresh."""
    while True:
        try:
            refresh_playlist()
            time.sleep(3600)
        except Exception as e:
            logging.error(f"Error refreshing playlist: {e}")
            time.sleep(600)


# -----------------------
# MAIN ENTRY
# -----------------------

if __name__ == "__main__":
    load_cache()
    refresh_playlist()

    # Download first track if not already cached
    if not CACHE.get("kas_ranker"):
        if QUEUE:
            first = QUEUE.pop(0)
            download_track(first)
            threading.Thread(target=predownload_next, daemon=True).start()

    threading.Thread(target=background_worker, daemon=True).start()

    logging.info("🚀 YouTube Radio started successfully!")
    logging.info("🌐 Open http://0.0.0.0:8000 to access the UI.")
    app.run(host="0.0.0.0", port=8000, debug=False)