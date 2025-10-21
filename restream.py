import os
import time
import threading
import logging
import subprocess
import json
from flask import Flask, Response, render_template_string

# -----------------------
# CONFIG & LOGGING
# -----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

PLAYLIST_URL = "https://youtube.com/playlist?list=PLopzY4eFJ8dUvcGcOXs7aPIWoI1r-dump"
COOKIES_PATH = "/mnt/data/cookies.txt"
VIDEOS = []
CURRENT_INDEX = 0
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
audio { width: 90%; margin-top: 20px; }
button { background: #0f0; color: #000; border: none; padding: 10px 20px; margin: 10px; border-radius: 8px; font-weight: bold; }
</style>
</head>
<body>
<h2>🎧 YouTube Continuous Restream</h2>
<p id="status">Loading stream...</p>
<audio id="player" controls autoplay></audio>
<script>
async function startStream() {
  const player = document.getElementById('player');
  const status = document.getElementById('status');
  while (true) {
    try {
      player.src = '/stream?nocache=' + Date.now();
      player.play();
      status.innerText = '🎵 Playing live audio...';
      await new Promise(r => player.onended = r);
    } catch(e) {
      status.innerText = '⚠️ Reconnecting...';
      await new Promise(r => setTimeout(r, 5000));
    }
  }
}
startStream();
</script>
</body>
</html>
"""

# -----------------------
# LOAD PLAYLIST
# -----------------------
def load_playlist():
    global VIDEOS
    try:
        logging.info(f"Loading playlist: {PLAYLIST_URL}")
        result = subprocess.run(
            [
                "yt-dlp", "--flat-playlist", "-J", PLAYLIST_URL,
                "--cookies", COOKIES_PATH
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        VIDEOS = [f"https://www.youtube.com/watch?v={e['id']}" for e in data.get("entries", [])]
        logging.info(f"Loaded {len(VIDEOS)} videos from playlist")
    except Exception as e:
        logging.error(f"Failed to load playlist: {e}")
        VIDEOS = []

# -----------------------
# GET NEXT VIDEO
# -----------------------
def get_next_video():
    global CURRENT_INDEX
    with LOCK:
        if not VIDEOS:
            load_playlist()
        if not VIDEOS:
            logging.warning("No videos to play.")
            return None
        url = VIDEOS[CURRENT_INDEX % len(VIDEOS)]
        CURRENT_INDEX += 1
        return url

# -----------------------
# STREAM ENDPOINT
# -----------------------
@app.route("/stream")
def stream():
    url = get_next_video()
    if not url:
        return "No videos available", 503

    logging.info(f"Streaming: {url}")
    # Use ffmpeg for audio-only
    process = subprocess.Popen(
        ["yt-dlp", "-f", "bestaudio", "-o", "-", url, "--cookies", COOKIES_PATH, "--quiet"],
        stdout=subprocess.PIPE
    )

    def generate():
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                break
            yield chunk
        process.kill()

    return Response(generate(), content_type="audio/mpeg")

# -----------------------
# HOME PAGE
# -----------------------
@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE)

# -----------------------
# BACKGROUND REFRESH
# -----------------------
def playlist_refresher():
    while True:
        load_playlist()
        time.sleep(1800)  # refresh every 30 minutes

# -----------------------
# MAIN
# -----------------------
if __name__ == "__main__":
    threading.Thread(target=playlist_refresher, daemon=True).start()
    load_playlist()
    app.run(host="0.0.0.0", port=5000)