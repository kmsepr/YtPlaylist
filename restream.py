import subprocess
import json
import logging
import threading
import time
from flask import Flask, Response, stream_with_context

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIES_PATH = "/mnt/data/cookies.txt"
REFRESH_INTERVAL = 1200  # Refresh every 20 minutes

CHANNELS = {
    "max": "https://youtube.com/@maxvelocitywx/videos",
    "eftguru": "https://youtube.com/@eftguru-ql8dk/videos",
    "anurag": "https://youtube.com/@anuragtalks1/videos",
}

VIDEO_CACHE = {name: None for name in CHANNELS}


def fetch_latest_video_url(name, channel_url):
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
        video_id = data['entries'][0]['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"✅ [{name}] Cached: {video_url}")
        return video_url

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ [{name}] yt-dlp failed: {e}")
        logging.error(f"[{name}] yt-dlp stderr:\n{e.stderr.strip()}")
        return None
    except Exception as e:
        logging.error(f"❌ [{name}] General error: {e}")
        return None


def update_video_cache():
    while True:
        for name, url in CHANNELS.items():
            logging.info(f"🔄 Fetching latest video for [{name}]")
            video_url = fetch_latest_video_url(name, url)
            if video_url:
                VIDEO_CACHE[name] = video_url
            else:
                logging.warning(f"⚠️ [{name}] No video found or fetch failed.")
            time.sleep(2)  # avoid 429 by spacing calls
        logging.info(f"✅ Cache refresh complete. Waiting {REFRESH_INTERVAL}s\n")
        time.sleep(REFRESH_INTERVAL)


@app.route("/<channel>.mp3")
def stream_channel(channel):
    if channel not in CHANNELS:
        return "Invalid channel", 404

    video_url = VIDEO_CACHE.get(channel)
    if not video_url:
        logging.warning(f"⏳ [{channel}] Not cached yet or fetch failed")
        return "Video not cached yet. Please try again shortly.", 503

    logging.info(f"🎧 [{channel}] Streaming from cached URL")

    def generate():
        yt = subprocess.Popen([
            "yt-dlp",
            "-f", "bestaudio",
            "--cookies", COOKIES_PATH,
            "--user-agent", FIXED_USER_AGENT,
            "-o", "-", video_url
        ], stdout=subprocess.PIPE)

        ff = subprocess.Popen([
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "mp3",
            "-ab", "64k",
            "-ar", "22050",
            "-ac", "1",
            "-hide_banner",
            "-loglevel", "quiet",
            "pipe:1"
        ], stdin=yt.stdout, stdout=subprocess.PIPE)

        yt.stdout.close()
        while True:
            chunk = ff.stdout.read(4096)
            if not chunk:
                break
            yield chunk

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


@app.route("/")
def index():
    links = "".join(f'<li><a href="/{name}.mp3">{name}</a></li>' for name in CHANNELS)
    return f"<h3>YouTube Podcast</h3><ul>{links}</ul>"


# Start the background cache thread
threading.Thread(target=update_video_cache, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)