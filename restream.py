import subprocess
import json
import time
import random
import os
from datetime import datetime
from flask import Flask, Response, stream_with_context, abort

app = Flask(__name__)

# 📂 Cookies file (Koyeb)
COOKIES_PATH = "/mnt/data/cookies.txt"

# 🎧 Define all playlists here
PLAYLISTS = {
    "kasranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    # Add more here later
}

# 📦 Cache directory
CACHE_DIR = "/mnt/data"
CACHE_EXPIRY_HOURS = 6


# ---------------------------
# 🔹 Helper Functions
# ---------------------------
def get_cache_path(channel):
    return os.path.join(CACHE_DIR, f"cache_{channel}.json")


def load_cached_playlist(channel):
    """Return cached playlist if still valid"""
    path = get_cache_path(channel)
    if not os.path.exists(path):
        return None
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    if age_hours > CACHE_EXPIRY_HOURS:
        print(f"🕒 Cache expired for {channel} ({age_hours:.1f}h old)")
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
            print(f"✅ Loaded {len(data)} items from cache for {channel}")
            return data
    except Exception as e:
        print("⚠️ Cache read error:", e)
        return None


def save_playlist_cache(channel, videos):
    """Write playlist to cache"""
    try:
        with open(get_cache_path(channel), "w") as f:
            json.dump(videos, f)
        print(f"💾 Saved {len(videos)} items to cache for {channel}")
    except Exception as e:
        print("⚠️ Cache write error:", e)


def fetch_playlist_videos(playlist_url, channel):
    """Fetch fresh playlist via yt-dlp, then cache"""
    print(f"📜 Fetching fresh playlist for {channel} ...", flush=True)
    result = subprocess.run(
        ["yt-dlp", "--cookies", COOKIES_PATH, "-j", "--flat-playlist", playlist_url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"❌ Playlist fetch failed for {channel}:", result.stderr)
        return []
    try:
        videos = [json.loads(line)["url"] for line in result.stdout.splitlines() if line.strip()]
        save_playlist_cache(channel, videos)
        return videos
    except Exception as e:
        print(f"⚠️ Parse error for {channel}: {e}")
        return []


def get_playlist_videos(channel, playlist_url):
    """Use cache if valid, else fetch"""
    cached = load_cached_playlist(channel)
    if cached:
        return cached
    videos = fetch_playlist_videos(playlist_url, channel)
    return videos if videos else cached or []


def get_audio_url(video_id):
    result = subprocess.run(
        ["yt-dlp", "--cookies", COOKIES_PATH, "-f", "bestaudio", "-g", f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ---------------------------
# 🔹 Stream Route
# ---------------------------
@app.route("/radio/<channel>")
def radio_stream(channel):
    if channel not in PLAYLISTS:
        return abort(404, f"No such channel: {channel}")

    playlist_url = PLAYLISTS[channel]
    print(f"🎧 Starting stream for {channel}: {playlist_url}", flush=True)

    def generate():
        while True:
            videos = get_playlist_videos(channel, playlist_url)
            if not videos:
                yield b""
                return
            random.shuffle(videos)
            for vid in videos:
                audio_url = get_audio_url(vid)
                if not audio_url:
                    continue
                print(f"▶️ Now playing {vid} from {channel}", flush=True)
                process = subprocess.Popen(
                    ["ffmpeg", "-re", "-i", audio_url, "-vn", "-c:a", "libmp3lame",
                     "-b:a", "128k", "-f", "mp3", "-"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )
                try:
                    for chunk in iter(lambda: process.stdout.read(4096), b""):
                        yield chunk
                except GeneratorExit:
                    process.kill()
                    return
                finally:
                    process.kill()
            time.sleep(5)

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


# ---------------------------
# 🔹 Homepage
# ---------------------------
@app.route("/")
def home():
    html = "<h2>🎙️ YouTube Playlist Radio (Cached)</h2><ul>"
    for name in PLAYLISTS:
        html += f"<li><a href='/radio/{name}' target='_blank'>{name}</a></li>"
    html += "</ul><p>Cache refresh every {CACHE_EXPIRY_HOURS} hours 🕒</p>"
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)