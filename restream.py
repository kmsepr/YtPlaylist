import os
import subprocess
import json
import logging
import threading
import random
from flask import Flask, Response, stream_with_context

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Proxy setup (optional)
PROXY = os.getenv("YTDLP_PROXY", "socks5h://127.0.0.1:9050")  # Change to http://... if needed
COOKIES_PATH = "/mnt/data/cookies.txt"
FIXED_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
]

CHANNELS = {
    "max": "https://youtube.com/@maxvelocitywx/videos",
    "eftguru": "https://youtube.com/@eftguru-ql8dk/videos",
    "anurag": "https://youtube.com/@anuragtalks1/videos",
}

VIDEO_CACHE = {name: None for name in CHANNELS}


def fetch_latest_video_url(name, url):
    try:
        result = subprocess.run([
            "yt-dlp",
            "--proxy", PROXY,
            "--dump-single-json",
            "--playlist-end", "1",
            "--cookies", COOKIES_PATH,
            "--user-agent", random.choice(FIXED_USER_AGENTS),
            url
        ], capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)
        video_id = data['entries'][0]['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"✅ [{name}] Video fetched: {video_url}")
        return video_url

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ [{name}] yt-dlp error: {e.stderr.strip()}")
    except Exception as e:
        logging.error(f"❌ [{name}] General error: {e}")
    return None


def update_cache():
    while True:
        for name, url in CHANNELS.items():
            VIDEO_CACHE[name] = fetch_latest_video_url(name, url)
        threading.Event().wait(900)  # Refresh every 15 min


@app.route("/")
def index():
    links = "\n".join(f'<li><a href="/{name}.mp3">{name}</a></li>' for name in CHANNELS)
    return f"<h3>YouTube Audio Stream</h3><ul>{links}</ul>"


@app.route("/<channel>.mp3")
def stream_channel(channel):
    if channel not in CHANNELS:
        return "Invalid channel", 404

    video_url = VIDEO_CACHE.get(channel)
    if not video_url:
        logging.warning(f"⏳ [{channel}] Not cached. Trying fetch...")
        video_url = fetch_latest_video_url(channel, CHANNELS[channel])
        if not video_url:
            return "Unable to fetch video", 503

    logging.info(f"🎧 [{channel}] Streaming: {video_url}")

    def generate():
        yt = subprocess.Popen([
            "yt-dlp", "-f", "bestaudio",
            "--proxy", PROXY,
            "--cookies", COOKIES_PATH,
            "--user-agent", random.choice(FIXED_USER_AGENTS),
            "-o", "-", video_url
        ], stdout=subprocess.PIPE)

        ff_env = os.environ.copy()
        ff_env["http_proxy"] = PROXY
        ff_env["https_proxy"] = PROXY

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
        ], stdin=yt.stdout, stdout=subprocess.PIPE, env=ff_env)

        yt.stdout.close()
        while True:
            chunk = ff.stdout.read(4096)
            if not chunk:
                break
            yield chunk

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


if __name__ == "__main__":
    threading.Thread(target=update_cache, daemon=True).start()
    app.run(host="0.0.0.0", port=8000)