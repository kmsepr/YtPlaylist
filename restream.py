import os
import time
import threading
import logging
import subprocess
from datetime import datetime
from flask import Flask, request, send_file, render_template_string, Response, redirect, url_for, jsonify

# ==============================================================
# ⚙️ Setup
# ==============================================================

app = Flask(__name__)
CACHE_DIR = "youtube_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRY_HOURS = 24
download_locks = {}

STATIONS = {
    "Radio Jornal": {
        "url": "https://player-ne10-radiojornal-app.stream.uol.com.br/live/radiojornalrecifeapp.m3u8",
        "quality": "medium"
    }
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==============================================================
# 🧹 Cache cleanup thread
# ==============================================================

def cleanup_cache():
    while True:
        now = time.time()
        for f in os.listdir(CACHE_DIR):
            path = os.path.join(CACHE_DIR, f)
            if os.path.isfile(path):
                age = now - os.path.getmtime(path)
                if age > CACHE_EXPIRY_HOURS * 3600:
                    try:
                        os.remove(path)
                        logging.info(f"🧹 Deleted expired cache: {f}")
                    except Exception as e:
                        logging.error(f"⚠️ Failed to delete {f}: {e}")
        time.sleep(3600)

threading.Thread(target=cleanup_cache, daemon=True).start()

# ==============================================================
# 🏠 Root index
# ==============================================================

@app.route("/")
def home():
    return """
    <html><head><title>Media Tools</title></head>
    <body style='font-family:sans-serif;text-align:center;'>
        <h2>🎧 Media Toolkit</h2>
        <p><a href='/yt'>🎵 YouTube → MP3 Converter</a></p>
        <p><a href='/radio'>📻 Custom Internet Radio</a></p>
    </body></html>
    """

# ==============================================================
# 🎧 YouTube → MP3 Section
# ==============================================================

@app.route("/yt")
def yt_index():
    files = sorted(
        [f for f in os.listdir(CACHE_DIR) if f.endswith(".mp3")],
        key=lambda x: os.path.getmtime(os.path.join(CACHE_DIR, x)),
        reverse=True,
    )
    html = """
    <html><head><title>YouTube → MP3 (16kbps)</title></head>
    <body style='font-family:sans-serif;text-align:center;'>
        <h2>YouTube → MP3 Converter</h2>
        <form action="/yt/download" method="post">
            <input name="url" placeholder="Paste YouTube URL" style="width:60%;padding:6px;">
            <button type="submit">Convert</button>
        </form>
        <h3>Cached Files (expires after 1 day)</h3>
        <ul style="list-style:none;padding:0;">
        {% for f in files %}
          <li><a href="/yt/cache/{{f}}">{{f}}</a></li>
        {% endfor %}
        </ul>
    </body></html>
    """
    return render_template_string(html, files=files)

@app.route("/yt/download", methods=["POST"])
def yt_download_audio():
    url = request.form.get("url")
    if not url:
        return "Missing URL", 400

    vid = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1]
    out_path = os.path.join(CACHE_DIR, f"{vid}.mp3")

    if os.path.exists(out_path):
        logging.info(f"✅ Using cached: {out_path}")
        return send_file(out_path, as_attachment=True)

    if url in download_locks:
        logging.info(f"⚠️ Already downloading: {url}")
        download_locks[url].join()
        if os.path.exists(out_path):
            return send_file(out_path, as_attachment=True)
        return "Download failed", 500

    def run_download():
        try:
            cmd = [
                "yt-dlp",
                "-f", "91/bestaudio[ext=m4a]/bestaudio/worst",
                "--no-playlist",
                "-o", f"{CACHE_DIR}/%(id)s.%(ext)s",
                url,
            ]
            logging.info("🚀 Downloading using format 91 (lowest MP4 available)")
            subprocess.run(cmd, check=True)

            downloaded_file = None
            for ext in ("mp4", "m4a", "webm"):
                candidate = os.path.join(CACHE_DIR, f"{vid}.{ext}")
                if os.path.exists(candidate):
                    downloaded_file = candidate
                    break
            if not downloaded_file:
                raise FileNotFoundError("Downloaded file not found.")

            cmd_ffmpeg = [
                "ffmpeg", "-y", "-i", downloaded_file,
                "-ac", "1", "-b:a", "16k", out_path
            ]
            logging.info(f"🎧 Converting to mono 16kbps MP3: {out_path}")
            subprocess.run(cmd_ffmpeg, check=True)
            os.remove(downloaded_file)
            logging.info(f"✅ Done and cleaned: {downloaded_file}")

        except Exception as e:
            logging.error(f"❌ Conversion failed: {e}")
        finally:
            download_locks.pop(url, None)

    t = threading.Thread(target=run_download)
    download_locks[url] = t
    t.start()
    t.join()

    if os.path.exists(out_path):
        return send_file(out_path, as_attachment=True)
    return "Conversion failed", 500

@app.route("/yt/cache/<path:filename>")
def yt_get_cache(filename):
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found", 404

# ==============================================================
# 📻 Radio Section
# ==============================================================

@app.route("/radio", methods=["GET", "POST"])
def radio_home():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("url", "").strip()
        quality = request.form.get("quality", "medium")
        if name and url:
            STATIONS[name] = {"url": url, "quality": quality}
        return redirect(url_for("radio_home"))

    html = """
    <!doctype html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Radio Home</title>
        <style>
            body { font-family: sans-serif; text-align:center; background:#111; color:#eee; }
            input, select, button { padding:6px; margin:4px; border-radius:8px; border:none; }
            input, select { width:70%; max-width:250px; }
            .station { background:#222; margin:6px auto; padding:10px; border-radius:10px; width:90%; max-width:300px; }
            .copy-btn, .del-btn { margin-top:5px; background:#444; color:#fff; border:none; padding:6px 10px; border-radius:8px; }
            .copy-btn:hover, .del-btn:hover { background:#666; }
            a { color:#4cf; text-decoration:none; }
        </style>
        <script>
        function copyURL(station, quality){
            const url = window.location.origin + '/radio/stream/' + encodeURIComponent(station) + '?quality=' + quality;
            navigator.clipboard.writeText(url).then(()=>{ alert('Copied: ' + url); });
        }
        function deleteStation(name){
            if(confirm('Delete ' + name + '?')){
                fetch('/radio/delete/' + encodeURIComponent(name), {method:'POST'}).then(()=>location.reload());
            }
        }
        </script>
    </head>
    <body>
        <h2>📻 Add Station</h2>
        <form method="post">
            <input name="name" placeholder="Station Name" required><br>
            <input name="url" placeholder="Stream URL" required><br>
            <select name="quality">
                <option value="small">Small (32kbps)</option>
                <option value="medium" selected>Medium (64kbps)</option>
                <option value="best">Best (128kbps)</option>
            </select><br>
            <button type="submit">Add Station</button>
        </form>
        <h3>🎶 Created stations</h3>
        {% for name, info in stations.items() %}
        <div class="station">
            <a href="{{ url_for('radio_play_station', name=name) }}">{{ name }}</a><br>
            <button class="copy-btn" onclick="copyURL('{{ name }}', '{{ info.quality }}')">Copy URL</button>
            <button class="del-btn" onclick="deleteStation('{{ name }}')">Delete</button>
        </div>
        {% else %}
        <p>No stations yet.</p>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(html, stations=STATIONS)

@app.route("/radio/delete/<name>", methods=["POST"])
def radio_delete(name):
    if name in STATIONS:
        del STATIONS[name]
    return jsonify({"status": "deleted"})

@app.route("/radio/stream/<name>")
def radio_play_station(name):
    if name not in STATIONS:
        return "Station not found", 404

    info = STATIONS[name]
    audio_url = info["url"]
    quality = request.args.get("quality", info.get("quality", "medium"))
    bitrate = {"small": "32k", "medium": "64k", "best": "128k"}.get(quality, "64k")

    def generate():
        cmd = [
            "ffmpeg", "-re", "-i", audio_url,
            "-b:a", bitrate, "-ac", "1", "-f", "mp3", "pipe:1", "-loglevel", "quiet"
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        try:
            for chunk in iter(lambda: process.stdout.read(4096), b""):
                yield chunk
        finally:
            process.terminate()

    return Response(generate(), mimetype="audio/mpeg")

# ==============================================================
# 🚀 Main
# ==============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
