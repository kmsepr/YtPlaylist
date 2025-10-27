import subprocess
import json
import time
import random
import sys
from flask import Flask, Response, stream_with_context

app = Flask(__name__)

# 🎧 Your YouTube playlist (KAS Ranker)
PLAYLIST_URL = "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ"

# 📂 Path to cookies file in Koyeb
COOKIES_PATH = "/mnt/data/cookies.txt"


# ---------------------------
# 🔹 Helper: run subprocess with real-time logs
# ---------------------------
def run_command(cmd):
    print(f"\n💻 Running command: {' '.join(cmd)}", flush=True)
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    output_lines = []
    for line in iter(process.stdout.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()
        output_lines.append(line)
    process.wait()
    return "\n".join(output_lines), process.returncode


# ---------------------------
# 🔹 Get playlist video IDs
# ---------------------------
def get_playlist_videos(playlist_url):
    print("\n📜 Fetching playlist videos...", flush=True)
    output, code = run_command([
        "yt-dlp", "--cookies", COOKIES_PATH,
        "-j", "--flat-playlist", playlist_url
    ])
    if code != 0:
        print(f"❌ Playlist fetch failed (code {code})")
        return []
    try:
        return [json.loads(line)["url"] for line in output.splitlines() if line.strip()]
    except Exception as e:
        print(f"⚠️ Playlist parse error: {e}")
        return []


# ---------------------------
# 🔹 Get direct audio stream URL
# ---------------------------
def get_audio_url(video_id):
    print(f"\n🎵 Resolving audio for video: {video_id}", flush=True)
    output, code = run_command([
        "yt-dlp", "--cookies", COOKIES_PATH,
        "-f", "bestaudio", "-g", f"https://www.youtube.com/watch?v={video_id}"
    ])
    if code != 0:
        print(f"❌ Audio URL fetch failed for {video_id} (code {code})")
        return None
    url = output.strip().splitlines()[-1] if output.strip() else None
    print(f"✅ Got audio URL for {video_id}: {url[:80]}...", flush=True)
    return url


# ---------------------------
# 🔹 Radio Stream Endpoint
# ---------------------------
@app.route("/kasradio")
def kas_radio():
    def generate():
        playlist = get_playlist_videos(PLAYLIST_URL)
        if not playlist:
            print("🚫 No videos found in playlist.")
            yield b""
            return

        # Keep looping forever
        while True:
            random.shuffle(playlist)
            for vid in playlist:
                audio_url = get_audio_url(vid)
                if not audio_url:
                    print(f"⚠️ Skipping video {vid} (no audio URL)")
                    continue

                print(f"\n▶️ Now streaming: {vid}")
                ffmpeg_cmd = [
                    "ffmpeg", "-re", "-i", audio_url,
                    "-vn", "-c:a", "libmp3lame", "-b:a", "128k",
                    "-f", "mp3", "-"
                ]
                print(f"🎬 Starting FFmpeg: {' '.join(ffmpeg_cmd)}", flush=True)

                process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )

                try:
                    for chunk in iter(lambda: process.stdout.read(4096), b""):
                        yield chunk
                except GeneratorExit:
                    print("🛑 Client disconnected.")
                    process.kill()
                    return
                except Exception as e:
                    print(f"⚠️ Stream error: {e}")
                finally:
                    process.kill()

                print(f"⏭️ Finished {vid}, moving to next video...", flush=True)

            print("🔁 Playlist loop complete, restarting...", flush=True)
            time.sleep(5)

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


# ---------------------------
# 🔹 Root Page / Health Check
# ---------------------------
@app.route("/")
def home():
    return """
    <h2>🎙️ KAS Ranker Radio (YouTube Restream)</h2>
    <p>Status: Running ✅</p>
    <p>Listen here → <a href="/kasradio">/kasradio</a></p>
    <p>Logs show real-time yt-dlp + ffmpeg activity in Koyeb console.</p>
    """


# ---------------------------
# 🔹 Entry Point
# ---------------------------
if __name__ == "__main__":
    print("🚀 Starting KAS Ranker YouTube Restream...", flush=True)
    app.run(host="0.0.0.0", port=8000)