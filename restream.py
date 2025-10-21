import os
import time
import threading
import logging
import subprocess
from flask import Flask, Response, render_template_string

# --------------------------------------------
# Logging & App Setup
# --------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

YOUTUBE_PLAYLIST = os.getenv(
    "YOUTUBE_PLAYLIST",
    "https://youtube.com/playlist?list=PLn3BMOY0H7UtVBWbP963mAYdmbRD8YbCi"
)
COOKIES_PATH = os.getenv("COOKIES_PATH", "/mnt/data/cookies.txt")
PORT = int(os.getenv("PORT", 5000))

playlist_videos = []
current_index = 0
playlist_lock = threading.Lock()

# --------------------------------------------
# Playlist Handling
# --------------------------------------------
def load_playlist():
    """Fetch YouTube playlist items using yt-dlp"""
    global playlist_videos
    logging.info("Loading playlist: %s", YOUTUBE_PLAYLIST)
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--cookies", COOKIES_PATH, "-J", YOUTUBE_PLAYLIST],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        import json
        data = json.loads(result.stdout)
        entries = data.get("entries", [])
        playlist_videos = [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if "id" in e]
        logging.info("Loaded %d videos from playlist", len(playlist_videos))
    except Exception as e:
        logging.error("Failed to load playlist: %s", e)

def get_next_video():
    """Return next video URL from the playlist"""
    global current_index
    with playlist_lock:
        if not playlist_videos:
            load_playlist()
        if not playlist_videos:
            return None
        url = playlist_videos[current_index]
        current_index = (current_index + 1) % len(playlist_videos)
        return url

# --------------------------------------------
# Audio Streamer
# --------------------------------------------
def stream_youtube_audio(url):
    """Stream audio from YouTube using yt-dlp + ffmpeg"""
    logging.info("Streaming: %s", url)
    ytdlp_cmd = [
        "yt-dlp", "-f", "bestaudio", "--cookies", COOKIES_PATH,
        "-o", "-", url
    ]
    ffmpeg_cmd = [
        "ffmpeg", "-i", "pipe:0", "-f", "mp3", "-acodec", "libmp3lame",
        "-ab", "128k", "-content_type", "audio/mpeg", "-"
    ]
    ytdlp = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ytdlp.stdout.close()
    return ffmpeg.stdout

# --------------------------------------------
# Flask Routes
# --------------------------------------------
@app.route("/")
def index():
    return render_template_string("""
        <html>
        <head><title>YouTube Playlist Radio</title></head>
        <body style="text-align:center; font-family:sans-serif;">
            <h2>🎧 YouTube Playlist Radio</h2>
            <audio controls autoplay src="/stream" style="width:90%;"></audio>
            <p>Streaming from:<br><b>{{ playlist }}</b></p>
        </body>
        </html>
    """, playlist=YOUTUBE_PLAYLIST)

@app.route("/stream")
def stream():
    """Continuously stream all videos in playlist"""
    def generate():
        while True:
            video = get_next_video()
            if not video:
                logging.warning("No videos to play.")
                time.sleep(15)
                continue
            try:
                ffmpeg_out = stream_youtube_audio(video)
                for chunk in iter(lambda: ffmpeg_out.read(4096), b""):
                    yield chunk
            except Exception as e:
                logging.error("Error streaming %s: %s", video, e)
                continue
    return Response(generate(), mimetype="audio/mpeg")

# --------------------------------------------
# Startup Hook (Flask version agnostic)
# --------------------------------------------
def init_on_startup():
    threading.Thread(target=load_playlist, daemon=True).start()

if hasattr(app, "before_serving"):
    app.before_serving(init_on_startup)
elif hasattr(app, "before_first_request"):
    app.before_first_request(init_on_startup)
else:
    init_on_startup()  # fallback if neither exists

# --------------------------------------------
# Run App
# --------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)