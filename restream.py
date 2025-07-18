import subprocess
import json
import time
import threading
from flask import Flask, Response

app = Flask(__name__)

# Configuration
FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIES_PATH = "/mnt/data/cookies.txt"
REFRESH_INTERVAL = 900  # 15 minutes

# Channels to monitor
CHANNELS = {
    "max": "https://www.youtube.com/@maxvelocitywx",
    "eftguru": "https://www.youtube.com/@eftguru-ql8dk",
    "anurag": "https://www.youtube.com/@anuragtalks1",
}

# Stores latest video URLs
LATEST_VIDEOS = {}

# ------------------- Core Functions -------------------

def fetch_latest_video(channel_url):
    try:
        result = subprocess.run([
            "yt-dlp",
            "--dump-single-json",
            "--playlist-end", "1",
            "--cookies", COOKIES_PATH,
            "--user-agent", FIXED_USER_AGENT,
            channel_url
        ], capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)
        entry = data["entries"][0]
        return f"https://www.youtube.com/watch?v={entry['id']}"
    except Exception as e:
        print(f"❌ Error fetching from {channel_url}: {e}")
        return None

def update_latest_videos():
    while True:
        print("🔄 Refreshing latest video URLs...")
        for key, url in CHANNELS.items():
            latest = fetch_latest_video(url)
            if latest:
                LATEST_VIDEOS[key] = latest
                print(f"✅ [{key}] {latest}")
            else:
                print(f"⚠️ [{key}] Failed to update")
        time.sleep(REFRESH_INTERVAL)

def stream_audio(youtube_url):
    ytdlp_cmd = [
        "yt-dlp", "-f", "bestaudio[ext=webm]/bestaudio",
        "-o", "-", "--cookies", COOKIES_PATH,
        "--user-agent", FIXED_USER_AGENT,
        youtube_url
    ]

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0", "-vn", "-acodec", "libmp3lame",
        "-b:a", "64k", "-ar", "22050", "-f", "mp3", "pipe:1"
    ]

    ytdlp = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
    ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp.stdout, stdout=subprocess.PIPE)

    def generate():
        try:
            while True:
                chunk = ffmpeg.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            ytdlp.kill()
            ffmpeg.kill()

    return Response(generate(), mimetype="audio/mpeg")

# ------------------- Routes -------------------

@app.route("/")
def index():
    return "<h3>Real-time YouTube Audio Streams:</h3>" + "<br>".join(
        f"<a href='/{k}.mp3'>{k}</a>" for k in CHANNELS
    )

@app.route("/<channel>.mp3")
def play(channel):
    url = LATEST_VIDEOS.get(channel)
    if not url:
        return f"No video available for {channel}. Try again shortly.", 503
    return stream_audio(url)

# ------------------- Start Background Thread -------------------

threading.Thread(target=update_latest_videos, daemon=True).start()

# ------------------- Run App -------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)