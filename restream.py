import subprocess
import threading
import logging
from flask import Flask, Response, render_template_string
from pathlib import Path
import os
import json
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

TMP_DIR = Path("/tmp/ytmp3")
TMP_DIR.mkdir(parents=True, exist_ok=True)

# Set a fixed user-agent and yt-dlp client
FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Replace with your own video links and channel names
YOUTUBE_STREAMS = {
    "kasranker": "https://www.youtube.com/watch?v=-jAQvE4idrE",
    "academis": "https://www.youtube.com/watch?v=Jo63QxF__Oc",
    "entridegree": "https://www.youtube.com/watch?v=YIoQ1tiRjhk",
    "talent": "https://www.youtube.com/watch?v=Vt-vYeFTmSg",
    "entri": "https://www.youtube.com/watch?v=ffZRx23xbnk"
}

VIDEO_CACHE = {}

def format_upload_month(upload_date):
    try:
        return datetime.strptime(upload_date, "%Y%m%d").strftime("%B %Y")
    except:
        return ""

def preload_video_info():
    for name, url in YOUTUBE_STREAMS.items():
        try:
            result = subprocess.run([
                "yt-dlp", "--skip-download", "--dump-json",
                "--cookies", "/mnt/data/cookies.txt",
                "--user-agent", FIXED_USER_AGENT,
                "--extractor-args", "youtube:player_client=tv",
                url
            ], capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            VIDEO_CACHE[name] = info
        except Exception as e:
            logging.warning(f"Failed to fetch info for {name}: {e}")

def download_and_convert(channel, video_url):
    final_path = TMP_DIR / f"{channel}.mp3"
    if final_path.exists():
        return final_path
    if not video_url:
        return None

    try:
        base_path = TMP_DIR / channel
        video_path = base_path.with_suffix(".mp4")
        thumb_path = base_path.with_suffix(".jpg")

        # Download fallback video+audio (format 18)
        subprocess.run([
            "yt-dlp",
            "-f", "18",
            "--output", str(base_path) + ".%(ext)s",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            "--extractor-args", "youtube:player_client=tv",
            video_url
        ], check=True)

        if not video_path.exists() or not thumb_path.exists():
            logging.error(f"Missing video or thumbnail for {channel}")
            return None

        info = VIDEO_CACHE.get(channel, {})
        title = info.get("title", channel)
        artist = info.get("channel", channel)
        album = format_upload_month(info.get("upload_date", ""))

        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(thumb_path),
            "-map", "0:a",
            "-map", "1:v",
            "-c:a", "libmp3lame",
            "-c:v", "mjpeg",
            "-b:a", "64k",
            "-ar", "22050",
            "-ac", "1",
            "-id3v2_version", "3",
            "-metadata", f"title={title}",
            "-metadata", f"album={album}",
            "-metadata", f"artist={artist}",
            "-disposition:v", "attached_pic",
            str(final_path)
        ], check=True)

        video_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)

        return final_path if final_path.exists() else None

    except Exception as e:
        logging.error(f"Error converting {channel}: {e}")
        return None

@app.route("/")
def index():
    html = """
    <h2>YouTube Audio Streams (SABR Bypass)</h2>
    <ul>
    {% for name in streams %}
      <li><a href="/stream/{{name}}">{{name}}</a></li>
    {% endfor %}
    </ul>
    """
    return render_template_string(html, streams=YOUTUBE_STREAMS.keys())

@app.route("/stream/<channel>")
def stream(channel):
    url = YOUTUBE_STREAMS.get(channel)
    if not url:
        return "Channel not found", 404

    audio_file = download_and_convert(channel, url)
    if not audio_file or not audio_file.exists():
        return "Download failed", 500

    def generate():
        with open(audio_file, "rb") as f:
            yield from f

    return Response(generate(), mimetype="audio/mpeg")

if __name__ == "__main__":
    threading.Thread(target=preload_video_info).start()
    app.run(host="0.0.0.0", port=8000)