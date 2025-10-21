import os
import json
import time
import logging
import subprocess
from flask import Flask, Response, request, render_template_string, redirect
import yt_dlp

# -----------------------------------------------------
# CONFIG & LOGGING
# -----------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

COOKIES_FILE = "/mnt/data/cookies.txt"
PLAYLIST_FILE = "playlists.json"
os.makedirs("cache", exist_ok=True)


# -----------------------------------------------------
# PLAYLIST STORAGE
# -----------------------------------------------------
def load_playlists():
    if os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "r") as f:
            return json.load(f)
    return {}

def save_playlists(data):
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


# -----------------------------------------------------
# ADD / FETCH PLAYLISTS
# -----------------------------------------------------
def add_playlist(name, url):
    data = load_playlists()
    data[name] = url
    save_playlists(data)
    logging.info(f"✅ Added playlist '{name}': {url}")

def get_playlist_videos(playlist_url):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "cookies": COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            entries = info.get("entries", [])
            return [f"https://www.youtube.com/watch?v={e['id']}" for e in entries if e.get("id")]
    except Exception as e:
        logging.error(f"Failed to load playlist {playlist_url}: {e}")
        return []


# -----------------------------------------------------
# STREAM GENERATOR (continuous play)
# -----------------------------------------------------
def generate_stream(playlist_url):
    videos = get_playlist_videos(playlist_url)
    if not videos:
        yield b""
        return

    for url in videos:
        logging.info(f"🎧 Streaming: {url}")
        cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio/best",
            "--no-playlist",
            "--cookies", COOKIES_FILE if os.path.exists(COOKIES_FILE) else "",
            "-o", "-",
            url
        ]
        try:
            proc = subprocess.Popen(
                [c for c in cmd if c],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            while True:
                chunk = proc.stdout.read(1024)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            logging.error(f"Stream error: {e}")
        finally:
            if proc:
                proc.kill()
        time.sleep(1)


# -----------------------------------------------------
# ROUTES
# -----------------------------------------------------
@app.route("/")
def home():
    playlists = load_playlists()
    return render_template_string("""
        <html>
        <head>
            <title>YouTube Restream Radio</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: sans-serif; background: #000; color: #0f0; text-align: center; }
                input, button { padding: 10px; margin: 5px; border-radius: 8px; border: none; }
                input { width: 80%; }
                button { background: #0f0; color: #000; font-weight: bold; }
                ul { list-style: none; padding: 0; }
                li { background: #111; padding: 10px; border-radius: 8px; margin: 8px; }
                audio { width: 90%; margin-top: 10px; }
                .urlbox { background: #111; margin-top: 15px; padding: 10px; border-radius: 8px; word-break: break-all; }
            </style>
        </head>
        <body>
            <h2>🎵 YouTube Playlist Radio</h2>
            <form method="post" action="/add">
                <input type="text" name="name" placeholder="Short name (e.g. dhruv)" required><br>
                <input type="url" name="url" placeholder="YouTube Playlist URL" required><br>
                <button type="submit">➕ Add Playlist</button>
            </form>

            <h3>📻 Active Playlists</h3>
            <ul>
            {% for name, url in playlists.items() %}
                <li>
                    <b>{{ name }}</b><br>
                    {{ url }}<br>
                    🔗 <a href="/playlist/{{name}}.mp3" target="_blank" style="color:#0f0;">{{ request.url_root }}playlist/{{name}}.mp3</a><br>
                    ▶️ <audio controls src="/playlist/{{name}}.mp3"></audio>
                </li>
            {% endfor %}
            </ul>
        </body>
        </html>
    """, playlists=playlists)


@app.route("/add", methods=["POST"])
def add_playlist_route():
    name = request.form.get("name", "").strip().lower()
    url = request.form.get("url", "").strip()
    if name and url:
        add_playlist(name, url)
    return redirect("/")


@app.route("/playlist/<name>.mp3")
def playlist_stream(name):
    playlists = load_playlists()
    if name not in playlists:
        return f"Playlist '{name}' not found", 404
    return Response(generate_stream(playlists[name]), mimetype="audio/mpeg")


# -----------------------------------------------------
# MAIN
# -----------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)