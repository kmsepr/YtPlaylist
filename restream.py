import os
import time
import json
import random
import subprocess
import logging
import threading
from flask import Flask, Response, stream_with_context

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

FIXED_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (Windows NT 10.0; WOW64)",
    "Mozilla/5.0 (Linux; Android 10; SM-G970F)",
]

COOKIES_PATH = "/mnt/data/cookies.txt"
REFRESH_INTERVAL = 1200  # 20 minutes
PROXY = ""  # Set to "socks5h://127.0.0.1:9050" for Tor or "http://ip:port" for public proxy

CHANNELS = {
    "max": "https://youtube.com/@maxvelocitywx/videos",
    "eftguru": "https://youtube.com/@eftguru-ql8dk/videos",
    "anurag": "https://youtube.com/@anuragtalks1/videos",
}

VIDEO_CACHE = {name: None for name in CHANNELS}


def fetch_latest_video_url(name, channel_url):
    try:
        cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--playlist-end", "1",
            "--extractor-args", "youtubetab:skip=authcheck",
            "--cookies", COOKIES_PATH,
            "--user-agent", random.choice(FIXED_USER_AGENTS),
        ]
        if PROXY:
            cmd += ["--proxy", PROXY]
        cmd.append(channel_url)

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        video_id = data['entries'][0]['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        logging.info(f"✅ [{name}] Latest video: {video_url}")
        return video_url

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ [{name}] yt-dlp error: {e.stderr.strip()}")
        return None
    except Exception as e:
        logging.error(f"❌ [{name}] General error: {e}")
        return None


def update_video_cache():
    while True:
        for name, url in CHANNELS.items():
            video_url = fetch_latest_video_url(name, url)
            if video_url:
                VIDEO_CACHE[name] = video_url
            else:
                logging.warning(f"⚠️ [{name}] No video found or fetch failed.")
        logging.info("✅ Cache refresh complete. Waiting %ds", REFRESH_INTERVAL)
        time.sleep(REFRESH_INTERVAL)


@app.route("/<channel>.mp3")
def stream_channel(channel):
    if channel not in CHANNELS:
        return "Invalid channel", 404

    video_url = VIDEO_CACHE.get(channel)
    if not video_url:
        logging.warning(f"⏳ [{channel}] Not cached yet or fetch failed")
        return "Video not cached yet. Please try again shortly.", 503

    logging.info(f"🎧 [{channel}] Streaming live audio")

    def generate():
        yt_cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "--cookies", COOKIES_PATH,
            "--user-agent", random.choice(FIXED_USER_AGENTS),
            "-o", "-", video_url
        ]
        if PROXY:
            yt_cmd += ["--proxy", PROXY]

        yt = subprocess.Popen(yt_cmd, stdout=subprocess.PIPE)

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
    return f"<h3>YouTube Audio Stream</h3><ul>{links}</ul>"


# Start the background cache fetcher
threading.Thread(target=update_video_cache, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)