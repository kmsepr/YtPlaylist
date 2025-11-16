# youtube_lite_flask_mp3.py
# Small Flask app: search YouTube, convert to 40 kbps mono MP3, cache results + thumbnails.

from flask import Flask, request, render_template_string, send_file, redirect, abort, url_for
import yt_dlp
import os
import pathlib
import threading
import requests

# === CONFIG ===
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_DIR = "cache"

# --- Global lock to prevent double conversions ---
active_lock = threading.Lock()
active_downloads = set()

app = Flask(__name__)
os.makedirs(CACHE_DIR, exist_ok=True)

# ===========================
#        HTML TEMPLATES
# ===========================

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
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;background:#214a6b;color:#fff;text-decoration:none; border:0; cursor:pointer}
.card{background:#111;padding:10px;border-radius:10px;margin:8px 0;text-align:left}
.small{font-size:0.85em;color:#aaa}
.audio-player{width:100%;margin-top:8px}
a.link{color:#4cf;text-decoration:none}
.footer{font-size:0.8em;color:#888;margin-top:12px}
img.thumb{width:120px;height:auto;border-radius:8px;display:block;margin-bottom:8px}
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
        <div><b>{{ f.mp3 }}</b></div>
        <audio class="audio-player" controls preload="none">
          <source src="{{ url_for('stream', name=f.mp3) }}" type="audio/mpeg">
        </audio>
        <div class="small">
          <a class="link" href="{{ url_for('cached_download', name=f.mp3) }}">Download</a>
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
.btn{display:inline-block;padding:8px 10px;border-radius:8px;margin:6px;background:#214a6b;color:#fff;text-decoration:none; border:0; cursor:pointer}
.small{font-size:0.85em;color:#aaa}
img.thumb{width:120px;height:auto;border-radius:8px;margin-bottom:8px}
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

# ===========================
#        UTILITIES
# ===========================

def safe_path_for_name(name: str) -> str:
    p = pathlib.Path(CACHE_DIR) / name
    try:
        resolved = p.resolve()
        base = pathlib.Path(CACHE_DIR).resolve()
        if base in resolved.parents or resolved == base:
            return str(resolved)
    except:
        pass
    raise ValueError("Invalid filename")

# ===========================
#  DOWNLOAD + CONVERSION
# ===========================

def download_and_convert_to_mp3(video_id: str) -> str:
    """
    Download YouTube video as 40 kbps mono MP3 with cached thumbnail.
    Returns the MP3 filename.
    """
    import pathlib
    import requests
    import os
    import yt_dlp

    mp3_path = os.path.join(CACHE_DIR, f"{video_id}.mp3")
    jpg_path = os.path.join(CACHE_DIR, f"{video_id}.jpg")

    # If MP3 exists, ensure thumbnail exists
    if os.path.exists(mp3_path):
        if not os.path.exists(jpg_path):
            _download_thumbnail(video_id, jpg_path)
        return f"{video_id}.mp3"

    url = f"https://www.youtube.com/watch?v={video_id}"

    # Extract metadata first (helps yt-dlp pick format)
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'cookiefile': COOKIES_PATH}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "")
    except Exception as e:
        print("Metadata extraction failed:", e)
        title = ""

    # Convert to MP3 40kbps mono
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(CACHE_DIR, f"{video_id}.%(ext)s"),
        'cookiefile': COOKIES_PATH,
        'prefer_ffmpeg': True,
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegPostProcessor'
        }],
        'postprocessor_args': [
            '-vn',           # strip video
            '-ac', '1',      # mono
            '-b:a', '40k',   # bitrate
            '-metadata', f"title={title}"  # embed title
        ]
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Download thumbnail
    _download_thumbnail(video_id, jpg_path)

    return f"{video_id}.mp3"


def _download_thumbnail(video_id: str, path: str):
    """Download YouTube thumbnail, fallback if fails"""
    thumb_urls = [
        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",   # 320x180
        f"https://i.ytimg.com/vi/{video_id}/default.jpg",     # 120x90 fallback
    ]
    for url in thumb_urls:
        try:
            r = requests.get(url, timeout=(4, 4))
            if r.ok:
                with open(path, "wb") as f:
                    f.write(r.content)
                return
        except Exception as e:
            continue
    # if all fail, remove old file if exists
    if os.path.exists(path):
        os.remove(path)

# ===========================
#          ROUTES
# ===========================

@app.route("/")
def home():
    files = sorted([f for f in os.listdir(CACHE_DIR) if f.endswith(".mp3")])
    items = []
    for f in files:
        thumb = f.replace(".mp3", ".jpg")
        items.append({
            "mp3": f,
            "thumb": thumb if os.path.exists(os.path.join(CACHE_DIR, thumb)) else None
        })
    return render_template_string(HOME_HTML, files=items)

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("home"))

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "cookiefile": COOKIES_PATH
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(f"ytsearch10:{q}", download=False)

    results = []
    for e in data.get("entries", []):
        vid = e.get("id")
        if not vid:
            continue
        thumb = f"https://i.ytimg.com/vi/{vid}/default.jpg"
        results.append(type("Obj", (object,), {
            "title": e.get("title"),
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
            return "Conversion in progress, try again shortly.", 429
        active_downloads.add(vid)

    try:
        download_and_convert_to_mp3(vid)
    finally:
        with active_lock:
            active_downloads.discard(vid)

    return redirect(url_for("home"))

@app.route("/stream/<name>")
def stream(name):
    try:
        path = safe_path_for_name(name)
    except:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    if name.endswith(".jpg"):
        return send_file(path, mimetype="image/jpeg")
    return send_file(path, mimetype="audio/mpeg", conditional=True)

@app.route("/cached/<name>")
def cached_download(name):
    try:
        path = safe_path_for_name(name)
    except:
        abort(404)

    if not os.path.exists(path):
        abort(404)

    return send_file(path, mimetype="audio/mpeg", as_attachment=True, download_name=name)

# ===========================
#        RUN SERVER
# ===========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)