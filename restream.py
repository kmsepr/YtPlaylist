# youtube_lite_flask_mp3.py
# Small Flask app: search YouTube, convert to 40 kbps mono MP3,
# cache results + cached thumbnails.

from flask import Flask, request, render_template_string, send_file, redirect, abort, url_for
import yt_dlp
import os
import pathlib
import threading
import requests

# ==========================
# CONFIG
# ==========================
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_DIR = "cache"

active_lock = threading.Lock()
active_downloads = set()

app = Flask(__name__)
os.makedirs(CACHE_DIR, exist_ok=True)

# ==========================
# HTML TEMPLATES
# ==========================

HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>YouTube Lite - MP3</title>
<style>
body{font-family:sans-serif;background:#0b0b0b;color:#eaeaea;text-align:center}
.container{max-width:420px;margin:8px auto}
.header{padding:10px}
input[type=text]{width:86%;padding:10px;border-radius:8px;border:0;margin-top:8px}
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;
background:#214a6b;color:#fff;text-decoration:none;border:0;cursor:pointer}
.card{background:#111;padding:10px;border-radius:10px;margin:8px 0;text-align:left}
.small{font-size:0.85em;color:#aaa}
audio{width:100%;margin-top:6px}
img.thumb{width:140px;height:auto;border-radius:8px;display:block;margin-bottom:8px}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h2>YouTube Lite (MP3 only)</h2>
    <form action="/search" method="get">
      <input name="q" placeholder="Search YouTube..." value="{{ query|default('') }}">
      <button class="btn" type="submit">Search</button>
    </form>
  </div>

  <h3>Cached MP3</h3>
  {% if files %}
    {% for f in files %}
      <div class="card">
        {% if f.thumb %}
          <img class="thumb" src="{{ url_for('stream', name=f.thumb) }}">
        {% endif %}
        <b>{{ f.title }}</b><br>
        <audio controls preload="none">
          <source src="{{ url_for('stream', name=f.mp3) }}" type="audio/mpeg">
        </audio>
        <div class="small">
          <a class="link" href="{{ url_for('cached_download', name=f.mp3) }}" style="color:#4cf">Download</a>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <p class="small">No cached files yet.</p>
  {% endif %}

  <div class="footer small" style="margin-top:12px">
    Tip: Click a search result to convert and cache as 40 kbps mono MP3.
  </div>
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
body{font-family:sans-serif;background:#0b0b0b;color:#eaeaea;text-align:center}
.container{max-width:420px;margin:8px auto}
.card{background:#111;padding:10px;border-radius:10px;margin:8px 0;text-align:left}
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;background:#214a6b;color:#fff;text-decoration:none;border:0;cursor:pointer}
.small{font-size:0.85em;color:#aaa}
img.thumb{width:140px;height:auto;border-radius:8px;margin-bottom:8px}
</style>
</head>
<body>
<div class="container">
  <h2>Results for '{{ query }}'</h2>
  {% if results %}
    {% for v in results %}
      <div class="card">
        {% if v.thumb %}
          <img class="thumb" src="{{ v.thumb }}">
        {% endif %}
        <b>{{ v.title }}</b>
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

# ==========================
# HELPERS
# ==========================

def safe_path_for_name(name: str) -> str:
    p = pathlib.Path(CACHE_DIR) / name
    try:
        p_resolved = p.resolve()
        cache_resolved = pathlib.Path(CACHE_DIR).resolve()
        if p_resolved.parent == cache_resolved:
            return str(p_resolved)
    except:
        pass
    raise ValueError("Invalid filename")

# ==========================
# DOWNLOAD + CONVERSION
# ==========================

def download_and_convert(video_id: str):
    mp3_name = f"{video_id}.mp3"
    jpg_name = f"{video_id}.jpg"

    mp3_path = os.path.join(CACHE_DIR, mp3_name)
    jpg_path = os.path.join(CACHE_DIR, jpg_name)

    # If already exists, skip
    if os.path.exists(mp3_path):
        return mp3_name, jpg_name

    # Get metadata only
    meta_opts = {
        "quiet": True,
        "cookiefile": COOKIES_PATH
    }

    with yt_dlp.YoutubeDL(meta_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        title = info.get("title", video_id)

    # Download + convert
    ydl_opts = {
        "format": "bestaudio",
        "outtmpl": mp3_path,
        "cookiefile": COOKIES_PATH,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "40"
        }],
        "postprocessor_args": ['-ac', '1', '-b:a', '40k'],
        "quiet": True,
        "no_warnings": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    # Download compact thumbnail (cached)
    thumb_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
    try:
        r = requests.get(thumb_url, timeout=10)
        if r.status_code == 200:
            with open(jpg_path, "wb") as f:
                f.write(r.content)
    except:
        pass

    return mp3_name, jpg_name


# ==========================
# ROUTES
# ==========================

@app.route("/")
def home():
    mp3s = [f for f in os.listdir(CACHE_DIR) if f.endswith(".mp3")]
    items = []

    for mp3 in sorted(mp3s):
        vid = mp3.replace(".mp3", "")
        jpg = f"{vid}.jpg"
        jpg_path = os.path.join(CACHE_DIR, jpg)

        title = vid

        # Optional: read title from filename or metadata storage (not implemented here)

        items.append({
            "mp3": mp3,
            "thumb": jpg if os.path.exists(jpg_path) else None,
            "title": title
        })

    return render_template_string(HOME_HTML, files=items)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect("/")

    opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "cookiefile": COOKIES_PATH
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(f"ytsearch10:{q}", download=False)

    results = []
    for e in data.get("entries", []):
        vid = e.get("id")
        if not vid:
            continue

        thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"

        results.append(type("Obj", (object,), {
            "title": e.get("title", vid),
            "id": vid,
            "thumb": thumb
        }))

    return render_template_string(SEARCH_HTML, results=results, query=q)


@app.route("/download")
def download():
    vid = request.args.get("id")
    if not vid:
        return "Missing ID", 400

    with active_lock:
        if vid in active_downloads:
            return "Conversion already running. Try again soon.", 429
        active_downloads.add(vid)

    try:
        download_and_convert(vid)
    except Exception as e:
        return f"Error: {e}", 500
    finally:
        with active_lock:
            active_downloads.discard(vid)

    return redirect("/")


@app.route("/stream/<name>")
def stream(name):
    try:
        path = safe_path_for_name(name)
    except:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    mimetype = "image/jpeg" if name.endswith(".jpg") else "audio/mpeg"
    return send_file(path, mimetype=mimetype, as_attachment=False)


@app.route("/cached/<name>")
def cached_download(name):
    try:
        path = safe_path_for_name(name)
    except:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    return send_file(path, mimetype="audio/mpeg", as_attachment=True, download_name=name)


# ==========================
# MAIN
# ==========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)