import subprocess
import json
from flask import Flask, Response

app = Flask(__name__)

FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIES_PATH = "/mnt/data/cookies.txt"

# List of channels
CHANNELS = {
    "max": "https://www.youtube.com/@maxvelocitywx",
    "eftguru": "https://www.youtube.com/@eftguru-ql8dk",
    "anurag": "https://www.youtube.com/@anuragtalks1",
}

def get_latest_video_url(channel_url):
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
        latest_video = data["entries"][0]
        return f"https://www.youtube.com/watch?v={latest_video['id']}"
    except Exception as e:
        print(f"❌ Failed to fetch video from {channel_url}: {e}")
        return None

def stream_audio(youtube_url):
    ytdlp_cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=webm]/bestaudio",
        "-o", "-",
        "--user-agent", FIXED_USER_AGENT,
        "--cookies", COOKIES_PATH,
        youtube_url
    ]

    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-vn", "-acodec", "libmp3lame",
        "-b:a", "64k", "-ar", "22050", "-f", "mp3",
        "pipe:1"
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

@app.route("/")
def home():
    return "<h3>Real-time YouTube Audio Streaming</h3>" + "<br>".join(
        [f"<a href='/{c}.mp3'>{c}</a>" for c in CHANNELS]
    )

@app.route("/<channel>.mp3")
def play(channel):
    channel_url = CHANNELS.get(channel)
    if not channel_url:
        return "Unknown channel", 404

    video_url = get_latest_video_url(channel_url)
    if not video_url:
        return "Failed to fetch latest video", 500

    return stream_audio(video_url)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)