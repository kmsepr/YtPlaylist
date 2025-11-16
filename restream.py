# youtube_lite_flask_mp3.py
# Small Flask app: search YouTube, convert to 40 kbps mono MP3, cache results,
# show cached MP3s on home with an audio streamer (no video).
# Requirements: pip install flask yt-dlp
#              ffmpeg must be installed on the system and available in PATH.

from flask import Flask, request, render_template_string, send_file, redirect, abort, url_for
import yt_dlp
import os
import uuid
import pathlib
import threading

app = Flask(__name__)
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# --- Templates (simple, "old Java" feel: compact, list-based UI) ---
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>YouTube Lite - MP3</title>
<style>
body{font-family: sans-serif; background:#0b0b0b; color:#eaeaea; text-align:center}
.container{max-width:420px;margin:8px auto}
.header{padding:10px}
input[type=text]{width:86%;padding:10px;border-radius:8px;border:0;margin-top:8px}
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;background:#214a6b;color:#fff;text-decoration:none}
.card{background:#111;padding:10px;border-radius:10px;margin:8px 0;text-align:left}
.small{font-size:0.85em;color:#aaa}
.audio-player{width:100%;margin-top:8px}
a.link{color:#4cf;text-decoration:none}
.footer{font-size:0.8em;color:#888;margin-top:12px}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h2>YouTube Lite (MP3 only)</h2>
    <form action="/search" method="get">
      <input name="q" placeholder="Search YouTube..." value="{{ query|default('') }}">
    </form>
  </div>

  <h3>Cached MP3</h3>
  {% if files %}
    {% for f in files %}
      <div class="card">
        <div><b>{{ f }}</b></div>
        <audio class="audio-player" controls preload="none">
          <source src="{{ url_for('stream', name=f) }}" type="audio/mpeg">
          Your browser does not support the audio element.
        </audio>
        <div class="small">
          <a class="link" href="{{ url_for('cached_download', name=f) }}">Download</a>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <p class="small">No cached files yet.</p>
  {% endif %}

  <div class="footer">Tip: Click a search result to convert and cache as 40 kbps mono MP3.</div>
</div>
</body>
</html>
"""

SEARCH_HTML = """
<!doctype html>
<html>
<head>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Search results</title>
<style>
body{font-family: sans-serif; background:#0b0b0b; color:#eaeaea; text-align:center}
.container{max-width:420px;margin:8px auto}
.card{background:#111;padding:10px;border-radius:10px;margin:8px 0;text-align:left}
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;background:#214a6b;color:#fff;text-decoration:none}
.small{font-size:0.85em;color:#aaa}
</style>
</head>
<body>
<div class="container">
  <h2>Results for '{{ query }}'</h2>
  {% if results %}
    {% for v in results %}
      <div class="card">
        <div><b>{{ v.title }}</b></div>
        <div class="small">ID: {{ v.id }}</div>
        <div style="margin-top:8px">
          <a class="btn" href="{{ url_for('download', id=v.id) }}">Get MP3</a>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <p class="small">No results</p>
  {% endif %}
  <div style="margin-top:8px"><a class="btn" href="/">⬅ Home</a></div>
</div>
</body>
</html>
"""

# --- Utilities ---

def safe_path_for_name(name: str) -> str:
    """Ensure the name refers to a file inside CACHE_DIR and prevents path traversal."""
    p = pathlib.Path(CACHE_DIR) / name
    try:
        p_resolved = p.resolve()
        cache_resolved = pathlib.Path(CACHE_DIR).resolve()
        if cache_resolved in p_resolved.parents or p_resolved == cache_resolved:
            return str(p_resolved)
    except Exception:
        pass
    raise ValueError("Invalid filename")

# --- YT-DLP / download helper ---

def download_and_convert_to_mp3(video_id: str) -> str:
    """Downloads given YouTube video id and converts to 40 kbps mono MP3.
    Returns the cached filename (basename) on success; raises on error.
    """
    filename = f"{uuid.uuid4()}.mp3"
    outpath = os.path.join(CACHE_DIR, filename)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outpath,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        # Force mono + 40 kbps
        "postprocessor_args": [
            "-ac", "1",
            "-b:a", "40k"
        ],
        "paths": {"home": CACHE_DIR}
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    if not os.path.exists(outpath):
        raise FileNotFoundError("Expected output not found")

    return filename

active_downloads = set()
active_lock = threading.Lock()

# --- Routes ---

@app.route("/")
def home():
    files = sorted(os.listdir(CACHE_DIR))
    return render_template_string(HOME_HTML, files=files)

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("home"))

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(f"ytsearch10:{q}", download=False)

    results = []
    for entry in data.get("entries", []):
        results.append(type("Obj", (object,), {
            "title": entry.get("title"),
            "id": entry.get("id")
        }))

    return render_template_string(SEARCH_HTML, results=results, query=q)

@app.route("/download")
def download():
    vid = request.args.get("id")
    if not vid:
        return "Missing ID", 400

    with active_lock:
        if vid in active_downloads:
            return "Conversion in progress for this video. Try again in a few seconds.", 429
        active_downloads.add(vid)

    try:
        download_and_convert_to_mp3(vid)
    except Exception as e:
        return f"Error while converting: {e}", 500
    finally:
        with active_lock:
            active_downloads.discard(vid)

    return redirect(url_for('home'))

@app.route('/stream/<name>')
def stream(name):
    try:
        path = safe_path_for_name(name)
    except ValueError:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    return send_file(path, mimetype='audio/mpeg', as_attachment=False, conditional=True)

@app.route('/cached/<name>')
def cached_download(name):
    try:
        path = safe_path_for_name(name)
    except ValueError:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    return send_file(path, mimetype='audio/mpeg', as_attachment=True, download_name=name)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)