import os
import time
import glob
import threading
import subprocess
from datetime import datetime, timedelta
from flask import Flask, request, send_file, render_template_string, abort

app = Flask(__name__)

# -------------------------------
# 📂 Basic config
# -------------------------------
MP3_DIR = "youtube_cache"
COOKIES_FILE = "/mnt/data/cookies.txt"
os.makedirs(MP3_DIR, exist_ok=True)
CACHE_DURATION = 86400  # 1 day (in seconds)

# -------------------------------
# 🧹 Auto cleanup thread
# -------------------------------
def cleanup_old_files():
    while True:
        now = time.time()
        for f in glob.glob(f"{MP3_DIR}/*.mp3"):
            if now - os.path.getmtime(f) > CACHE_DURATION:
                os.remove(f)
        time.sleep(3600)  # check every hour

threading.Thread(target=cleanup_old_files, daemon=True).start()

# -------------------------------
# 🏠 Home route - list cached MP3s
# -------------------------------
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
      <title>YouTube to MP3 Cache</title>
      <style>
        body { font-family: sans-serif; padding: 10px; }
        input[type=text] { width: 80%; padding: 6px; }
        button { padding: 6px 10px; }
        table { border-collapse: collapse; width: 100%; margin-top: 15px; }
        td, th { border: 1px solid #ccc; padding: 6px; }
      </style>
    </head>
    <body>
      <h2>🎵 YouTube to MP3 Converter (cached 1 day)</h2>
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
            <td><a href="/play/{{ f.name }}">Play</a></td>
          </tr>
        {% endfor %}
      </table>
    </body>
    </html>
    """, files=files)

# -------------------------------
# ▶️ Convert route
# -------------------------------
@app.route("/convert", methods=["POST"])
def convert():
    url = request.form.get("url")
    if not url:
        abort(400, "Missing URL")

    # Extract video ID or safe filename
    vid_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1]
    output_path = os.path.join(MP3_DIR, f"{vid_id}.mp3")

    # If cached already
    if os.path.exists(output_path):
        return f"Already cached: <a href='/play/{os.path.basename(output_path)}'>Play</a>"

    # Run yt-dlp
    cmd = [
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "-x", "--audio-format", "mp3",
        "--audio-quality", "64K",
        "-o", os.path.join(MP3_DIR, "%(id)s.%(ext)s"),
        url,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(output_path):
        return "❌ Failed to download or convert."

    return f"✅ Converted: <a href='/play/{os.path.basename(output_path)}'>Play</a>"

# -------------------------------
# 🎧 Play route
# -------------------------------
@app.route("/play/<filename>")
def play(filename):
    path = os.path.join(MP3_DIR, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False, mimetype="audio/mpeg")

# -------------------------------
# 🚀 Run
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)