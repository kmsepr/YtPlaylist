import os
import time
import glob
import threading
import subprocess
import logging
from datetime import datetime
from flask import Flask, request, send_file, render_template_string, abort

# ====================================================
# ⚙️ Flask + Logging setup
# ====================================================
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

MP3_DIR = "youtube_cache"
COOKIES_FILE = "/mnt/data/cookies.txt"
CACHE_DURATION = 86400  # 1 day (in seconds)
os.makedirs(MP3_DIR, exist_ok=True)

# ====================================================
# 🧹 Cleanup old MP3 files (every hour)
# ====================================================
def cleanup_cache():
    while True:
        now = time.time()
        for f in glob.glob(f"{MP3_DIR}/*.mp3"):
            if now - os.path.getmtime(f) > CACHE_DURATION:
                logging.info(f"🗑️ Removing expired file: {f}")
                os.remove(f)
        time.sleep(3600)

threading.Thread(target=cleanup_cache, daemon=True).start()

# ====================================================
# 🏠 Home page - List cached MP3s
# ====================================================
@app.route("/")
def home():
    files = []
    for path in sorted(glob.glob(f"{MP3_DIR}/*.mp3"), key=os.path.getmtime, reverse=True):
        name = os.path.basename(path)
        size = os.path.getsize(path) // 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        files.append({"name": name, "size": size, "mtime": mtime})

    return render_template_string("""
    <html>
    <head>
      <title>YouTube → MP3 (Mono)</title>
      <style>
        body { font-family: sans-serif; background: #111; color: #eee; padding: 10px; }
        input[type=text] { width: 75%; padding: 6px; }
        button { padding: 6px 10px; background: #2b2; color: #fff; border: none; }
        a { color: #4cf; }
        table { border-collapse: collapse; width: 100%; margin-top: 15px; }
        td, th { border: 1px solid #333; padding: 5px; }
      </style>
    </head>
    <body>
      <h2>🎵 YouTube → MP3 Converter (Mono, Cached 1 Day)</h2>
      <form action="/convert" method="post">
        <input type="text" name="url" placeholder="Paste YouTube URL here" required>
        <button type="submit">Convert</button>
      </form>
      <h3>Cached MP3 Files</h3>
      <table>
        <tr><th>Title</th><th>Size (KB)</th><th>Saved</th><th>Play</th></tr>
        {% for f in files %}
        <tr>
          <td>{{ f.name }}</td>
          <td>{{ f.size }}</td>
          <td>{{ f.mtime }}</td>
          <td><a href="/play/{{ f.name }}">▶️</a></td>
        </tr>
        {% endfor %}
      </table>
    </body>
    </html>
    """, files=files)

# ====================================================
# ▶️ Conversion route
# ====================================================
@app.route("/convert", methods=["POST"])
def convert():
    url = request.form.get("url")
    if not url:
        abort(400, "Missing YouTube URL")

    # Get safe video ID
    vid_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1]
    output_path = os.path.join(MP3_DIR, f"{vid_id}.mp3")

    if os.path.exists(output_path):
        logging.info(f"🎵 Using cached MP3: {output_path}")
        return f"✅ Already cached: <a href='/play/{os.path.basename(output_path)}'>Play</a>"

    # yt-dlp + ffmpeg mono command
    cmd = [
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "-x", "--audio-format", "mp3",
        "--audio-quality", "64K",
        "--postprocessor-args", "ffmpeg:-ac 1 -loglevel info",
        "-o", os.path.join(MP3_DIR, "%(id)s.%(ext)s"),
        url,
    ]

    logging.info("🚀 Starting conversion")
    logging.info(f"URL: {url}")
    logging.info(f"Output: {output_path}")
    logging.info("Command: " + " ".join(cmd))

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    for line in process.stdout:
        logging.info(line.strip())

    process.wait()
    logging.info(f"✅ Conversion completed with exit code {process.returncode}")

    if not os.path.exists(output_path):
        logging.error("❌ Conversion failed or file not found")
        return "❌ Conversion failed. Check Koyeb logs for details."

    logging.info(f"✅ File saved: {output_path} ({os.path.getsize(output_path)//1024} KB)")
    return f"✅ Done: <a href='/play/{os.path.basename(output_path)}'>Play</a>"

# ====================================================
# 🎧 Play MP3
# ====================================================
@app.route("/play/<filename>")
def play(filename):
    path = os.path.join(MP3_DIR, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/mpeg", as_attachment=False)

# ====================================================
# 🚀 Run on Koyeb
# ====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)