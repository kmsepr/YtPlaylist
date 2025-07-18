import time
import subprocess
import json
import logging
import threading
from flask import Flask, Response, request, redirect

app = Flask(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Refresh every 20 minutes
REFRESH_INTERVAL = 1200

# Required for cookies-only access (place this on disk)
COOKIES_FILE = "/mnt/data/cookies.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Your YouTube channels
CHANNELS = {
    "max": "https://youtube.com/@maxvelocitywx/videos",
    "eftguru": "https://youtube.com/@eftguru-ql8dk/videos",
    "anurag": "https://youtube.com/@anuragtalks1/videos"
}

# Store latest video URLs
LATEST_VIDEOS = {name: None for name in CHANNELS}

# Fetch latest video for a given channel URL
def fetch_latest_video(channel_url):
    try:
        result = subprocess.run([
            "yt-dlp",
            "--dump-single-json",
            "--playlist-end", "1",
            "--cookies", COOKIES_FILE,
            "--user-agent", USER_AGENT,
            channel_url
        ], capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)
        video = data["entries"][0]
        return f"https://www.youtube.com/watch?v={video['id']}"

    except Exception as e:
        logging.error(f"❌ yt-dlp error for {channel_url}: {e}")
        return None

# Background thread to update latest video URLs
def update_latest_videos():
    while True:
        logging.info("🔄 Refreshing latest video URLs...")
        for key, url in CHANNELS.items():
            latest = fetch_latest_video(url)
            if latest:
                LATEST_VIDEOS[key] = latest
                logging.info(f"✅ [{key}] Latest video URL: {latest}")
            else:
                logging.warning(f"⚠️ [{key}] Failed to fetch video URL")
        time.sleep(REFRESH_INTERVAL)

# Stream redirect endpoint
@app.route("/<channel>")
def stream_channel(channel):
    if channel not in LATEST_VIDEOS:
        return f"Channel '{channel}' not found", 404
    url = LATEST_VIDEOS[channel]
    if url:
        return redirect(url)
    return f"No video found for {channel}", 503

# Homepage with links
@app.route("/")
def index():
    html = "<h3>📺 YouTube Live Streaming</h3><ul>"
    for ch in CHANNELS:
        html += f'<li><a href="/{ch}">{ch}</a></li>'
    html += "</ul>"
    return html

# Start thread
threading.Thread(target=update_latest_videos, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)