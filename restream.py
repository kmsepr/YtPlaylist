import os
import time
import threading
import logging
import subprocess
from datetime import datetime, timedelta
from flask import Flask, request, send_file, render_template_string

# ==============================================================
# ⚙️ Setup
# ==============================================================

app = Flask(__name__)
CACHE_DIR = "youtube_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRY_HOURS = 24
download_locks = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==============================================================
# 🧹 Clean up old cache
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
# 🏠 Home page
# ==============================================================

@app.route("/")
def index():
    files = sorted(
        [f for f in os.listdir(CACHE_DIR) if f.endswith(".mp3")],
        key=lambda x: os.path.getmtime(os.path.join(CACHE_DIR, x)),
        reverse=True,
    )
    html = """
    <html><head><title>YouTube → MP3 (16kbps)</title></head>
    <body style='font-family:sans-serif;text-align:center;'>
        <h2>YouTube → MP3 Converter</h2>
        <form action="/download" method="post">
            <input name="url" placeholder="Paste YouTube URL" style="width:60%;padding:6px;">
            <button type="submit">Convert</button>
        </form>
        <h3>Cached Files (expires after 1 day)</h3>
        <ul style="list-style:none;padding:0;">
        {% for f in files %}
          <li><a href="/cache/{{f}}">{{f}}</a></li>
        {% endfor %}
        </ul>
    </body></html>
    """
    return render_template_string(html, files=files)

# ==============================================================
# 🎧 Download Route (Format 91 forced)
# ==============================================================

@app.route("/download", methods=["POST"])
def download_audio():
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
                "--cookies", "/mnt/data/cookies.txt",
                "-o", f"{CACHE_DIR}/%(id)s.%(ext)s",
                url,
            ]
            logging.info("🚀 Downloading using format 91 (lowest MP4 available)")
            logging.info(f"Command: {' '.join(cmd)}")

            subprocess.run(cmd, check=True)

            # Find downloaded file
            downloaded_file = None
            for ext in ("mp4", "m4a", "webm"):
                candidate = os.path.join(CACHE_DIR, f"{vid}.{ext}")
                if os.path.exists(candidate):
                    downloaded_file = candidate
                    break

            if not downloaded_file:
                raise FileNotFoundError("Downloaded file not found.")

            # Convert to mono 16kbps MP3
            cmd_ffmpeg = [
                "ffmpeg", "-y",
                "-i", downloaded_file,
                "-ac", "1", "-b:a", "16k",
                out_path,
            ]
            logging.info(f"🎧 Converting to mono 16kbps MP3: {out_path}")
            subprocess.run(cmd_ffmpeg, check=True)

            os.remove(downloaded_file)
            logging.info(f"✅ Done and cleaned: {downloaded_file}")

        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Conversion failed: {e}")
        except Exception as e:
            logging.error(f"⚠️ Error: {e}")
        finally:
            download_locks.pop(url, None)

    t = threading.Thread(target=run_download)
    download_locks[url] = t
    t.start()
    t.join()

    if os.path.exists(out_path):
        return send_file(out_path, as_attachment=True)
    return "Conversion failed", 500

# ==============================================================
# 📦 Serve cached
# ==============================================================

@app.route("/cache/<path:filename>")
def get_cache(filename):
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "File not found", 404

# ==============================================================
# 🚀 Main
# ==============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)