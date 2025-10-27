import subprocess
import json
import time
import random
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# 🎧 Your YouTube playlist (KAS Ranker)
PLAYLIST_URL = "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ"

# 📂 Path to cookies file in Koyeb
COOKIES_PATH = "/mnt/data/cookies.txt"


# ---------------------------
# 🔹 Get all video IDs in playlist
# ---------------------------
def get_playlist_videos(playlist_url):
    print("📜 Fetching playlist videos...")
    result = subprocess.run(
        [
            "yt-dlp", "--cookies", COOKIES_PATH,
            "-j", "--flat-playlist", playlist_url
        ],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("❌ Failed to load playlist:", result.stderr)
        return []
    try:
        return [json.loads(line)["url"] for line in result.stdout.splitlines()]
    except Exception as e:
        print("⚠️ Playlist parse error:", e)
        return []


# ---------------------------
# 🔹 Get direct audio URL
# ---------------------------
def get_audio_url(video_id):
    result = subprocess.run(
        [
            "yt-dlp", "--cookies", COOKIES_PATH,
            "-f", "bestaudio", "-g", f"https://www.youtube.com/watch?v={video_id}"
        ],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ---------------------------
# 🔹 Flask route for radio streaming
# ---------------------------
@app.route("/kasradio")
def kas_radio():
    def generate():
        playlist = get_playlist_videos(PLAYLIST_URL)
        if not playlist:
            yield b""
            return

        # Shuffle playlist order each loop
        while True:
            random.shuffle(playlist)
            for vid in playlist:
                audio_url = get_audio_url(vid)
                if not audio_url:
                    print(f"⚠️ Skipping {vid} (no audio)")
                    continue
                print(f"▶️ Now playing: {vid}")

                # Stream audio via FFmpeg
                process = subprocess.Popen(
                    [
                        "ffmpeg", "-re", "-i", audio_url,
                        "-vn", "-c:a", "libmp3lame", "-b:a", "128k",
                        "-f", "mp3", "-"
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL
                )

                try:
                    for chunk in iter(lambda: process.stdout.read(4096), b""):
                        yield chunk
                except GeneratorExit:
                    process.kill()
                    return
                except Exception as e:
                    print("Stream error:", e)
                finally:
                    process.kill()

            print("🔁 Looping playlist again...")
            time.sleep(3)

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


# ---------------------------
# 🔹 Health check / root info
# ---------------------------
@app.route("/")
def home():
    return "<h3>🎙️ KAS Ranker Radio is live!</h3><p>Listen at <a href='/kasradio'>/kasradio</a></p>"


# ---------------------------
# 🔹 Run on Koyeb / localhost
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)