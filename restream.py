import os
import threading
import time
import subprocess
from flask import Flask, Response, request, render_template_string, redirect, url_for

# ----------------------------
# Configuration
# ----------------------------
COOKIES_PATH = os.environ.get("COOKIES_PATH", "/app/data/mnt/cookies.txt")
YTDLP_BIN = os.environ.get("YTDLP_BIN", "yt-dlp")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
PORT = int(os.environ.get("PORT", 5000))
AUTO_PLAYLIST_URL = os.environ.get("AUTO_PLAYLIST_URL", None)

app = Flask(__name__)

playlist = []
playlist_lock = threading.Lock()
current_index = 0

# ----------------------------
# HTML ADMIN PAGE
# ----------------------------
ADMIN_HTML = """
<!doctype html>
<title>YouTube Radio Admin</title>
<h1>YouTube Radio — Admin</h1>

{% if not auto_url %}
<form method="post" action="/admin/set_auto">
  <input name="url" placeholder="YouTube playlist URL" style="width:60%">
  <button type="submit">Set as auto-playlist</button>
</form>
{% else %}
<p><b>Auto-playlist:</b> {{auto_url}}</p>
<form method="post" action="/admin/clear_auto">
  <button type="submit">Clear auto playlist</button>
</form>
{% endif %}

<form method="post" action="/admin/add" style="margin-top:20px">
  <input name="url" placeholder="YouTube video or playlist URL" style="width:60%">
  <button type="submit">Add manually</button>
</form>

<form method="post" action="/admin/clear" style="margin-top:10px">
  <button type="submit">Clear playlist</button>
</form>

<h2>Playlist</h2>
<ol>
{% for i,u in playlist %}
  <li>{{u}}</li>
{% endfor %}
</ol>

<p>Stream endpoint: <a href="/stream">/stream</a></p>
"""

# ----------------------------
# Utilities
# ----------------------------
def extract_playlist_items(playlist_url):
    """Return list of video URLs in playlist."""
    cmd = [
        YTDLP_BIN, "--cookies", COOKIES_PATH,
        "--flat-playlist", "--print", "url", playlist_url
    ]
    try:
        out = subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=60
        )
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return ["https://www.youtube.com/watch?v=" + l if not l.startswith("http") else l for l in lines]
    except Exception as e:
        print("extract_playlist_items error:", e)
        return []


def yt_audio_url(url):
    """Extract best audio URL from YouTube video."""
    cmd = [
        YTDLP_BIN, "--cookies", COOKIES_PATH,
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "-g", url
    ]
    try:
        out = subprocess.check_output(
            cmd, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=30
        )
        return out.strip()
    except Exception as e:
        print("yt_audio_url error:", e)
        return None


def make_ffmpeg_proc(audio_url):
    """Launch ffmpeg subprocess for streaming audio."""
    try:
        cmd = [
            FFMPEG_BIN, "-loglevel", "quiet", "-i", audio_url,
            "-vn", "-acodec", "libmp3lame", "-b:a", "128k",
            "-f", "mp3", "-"
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE)
    except Exception as e:
        print("ffmpeg launch error:", e)
        return None


def ensure_auto_playlist_loaded():
    """Reload playlist from AUTO_PLAYLIST_URL if set."""
    global playlist
    if AUTO_PLAYLIST_URL:
        with playlist_lock:
            items = extract_playlist_items(AUTO_PLAYLIST_URL)
            if items:
                playlist = items.copy()
                print(f"Loaded {len(items)} items from auto playlist.")


def init_auto_playlist():
    """Initialize auto playlist on startup."""
    if AUTO_PLAYLIST_URL:
        ensure_auto_playlist_loaded()

# compatible with Flask 3.x
if hasattr(app, "before_serving"):
    app.before_serving(init_auto_playlist)
else:
    app.before_first_request(init_auto_playlist)

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    return redirect(url_for("admin"))


@app.route("/admin")
def admin():
    with playlist_lock:
        items = list(enumerate(playlist))
    return render_template_string(ADMIN_HTML, playlist=items, auto_url=AUTO_PLAYLIST_URL)


@app.route("/admin/set_auto", methods=["POST"])
def admin_set_auto():
    global AUTO_PLAYLIST_URL
    url = request.form.get("url", "").strip()
    if not url:
        return redirect(url_for("admin"))
    AUTO_PLAYLIST_URL = url
    ensure_auto_playlist_loaded()
    return redirect(url_for("admin"))


@app.route("/admin/clear_auto", methods=["POST"])
def admin_clear_auto():
    global AUTO_PLAYLIST_URL
    AUTO_PLAYLIST_URL = None
    with playlist_lock:
        playlist.clear()
    return redirect(url_for("admin"))


@app.route("/admin/add", methods=["POST"])
def admin_add():
    url = request.form.get("url", "").strip()
    if not url:
        return redirect(url_for("admin"))
    with playlist_lock:
        playlist.append(url)
    return redirect(url_for("admin"))


@app.route("/admin/clear", methods=["POST"])
def admin_clear():
    with playlist_lock:
        playlist.clear()
    return redirect(url_for("admin"))


@app.route("/stream")
def stream():
    global current_index

    def generate():
        while True:
            if AUTO_PLAYLIST_URL:
                ensure_auto_playlist_loaded()

            with playlist_lock:
                if not playlist:
                    time.sleep(1)
                    continue
                url = playlist[current_index % len(playlist)]
                current_index += 1

            audio_url = yt_audio_url(url)
            if not audio_url:
                time.sleep(1)
                continue

            proc = make_ffmpeg_proc(audio_url)
            if not proc or not proc.stdout:
                time.sleep(1)
                continue

            try:
                while True:
                    chunk = proc.stdout.read(16 * 1024)
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                print("Streaming error:", e)
            finally:
                if proc:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    headers = {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return Response(generate(), headers=headers)


# ----------------------------
# Main entry
# ----------------------------
if __name__ == "__main__":
    if not os.path.exists(COOKIES_PATH):
        print(f"Warning: cookies file missing at {COOKIES_PATH}")
    app.run(host="0.0.0.0", port=PORT, threaded=True)