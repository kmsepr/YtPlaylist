import os
import time
import glob
import threading
import subprocess
import logging
from datetime import datetime
from flask import Flask, request, send_file, abort

# =====================================================
# ⚙️ Configuration
# =====================================================
app = Flask(__name__)
MP3_DIR = "youtube_cache"
COOKIES_FILE = "/mnt/data/cookies.txt"
CACHE_DURATION = 86400  # 1 day

os.makedirs(MP3_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# =====================================================
# 🧹 Background cleanup
# =====================================================
def cleanup_cache():
    while True:
        now = time.time()
        for f in glob.glob(f"{MP3_DIR}/*.mp3"):
            if now - os.path.getmtime(f) > CACHE_DURATION:
                logging.info(f"🧹 Deleting expired cache: {f}")
                os.remove(f)
        time.sleep(3600)

threading.Thread(target=cleanup_cache, daemon=True).start()


# =====================================================
# 🏠 Home Page – list cached MP3s
# =====================================================
@app.route("/")
def home():
    files = []
    for f in sorted(glob.glob(f"{MP3_DIR}/*.mp3"), key=os.path.getmtime, reverse=True):
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        size_mb = os.path.getsize(f) / (1024 * 1024)
        files.append(f"<li>{os.path.basename(f)} - {size_mb:.2f} MB - {mtime}</li>")
    return f"""
    <h2>🎵 Cached MP3 Files</h2>
    <ul>{''.join(files) or '<li>No cached files yet</li>'}</ul>
    <form method='POST' action='/download'>
      <input name='url' placeholder='YouTube link' style='width:80%' required>
      <button type='submit'>Convert to 16 kbps MP3</button>
    </form>
    """


# =====================================================
# 🎧 Download + Convert
# =====================================================
@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url", "").strip()
    if not url:
        return "Missing URL", 400

    # Extract video ID or unique tag
    ytid = url.split("v=")[-1].split("&")[0].replace("/", "_")
    mp3_file = os.path.join(MP3_DIR, f"{ytid}.mp3")

    # If cached, return immediately
    if os.path.exists(mp3_file):
        logging.info(f"✅ Using cached MP3: {mp3_file}")
        return send_file(mp3_file, as_attachment=True)

    # -------------------------------------------------
    # Step 1: Download smallest audio format available
    # -------------------------------------------------
    logging.info(f"🎬 Downloading audio from: {url}")
    tmp_file = os.path.join(MP3_DIR, f"{ytid}.%(ext)s")
    ytdlp_cmd = [
        "yt-dlp",
        "-f",
        "bestaudio[ext=m4a][abr<=128]/bestaudio[ext=m4a]/bestaudio[abr<=128]/bestaudio",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "-o", tmp_file,
        "--progress",
        url,
    ]

    try:
        subprocess.run(ytdlp_cmd, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ yt-dlp failed: {e}")
        return "Download failed", 500

    # Find the downloaded file
    downloaded = None
    for f in glob.glob(f"{MP3_DIR}/{ytid}.*"):
        if not f.endswith(".mp3"):
            downloaded = f
            break
    if not downloaded:
        return "Download not found", 500

    # -------------------------------------------------
    # Step 2: Convert to 16 kbps mono MP3
    # -------------------------------------------------
    logging.info(f"🎧 Converting to 16 kbps mono MP3 → {mp3_file}")
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", downloaded,
        "-ac", "1",             # mono
        "-ar", "22050",         # sample rate
        "-b:a", "16k",          # 16 kbps target
        "-codec:a", "libmp3lame",
        "-map_metadata", "-1",  # remove tags
        mp3_file
    ]

    process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        logging.info(line.strip())
    process.wait()

    if process.returncode != 0:
        logging.error("❌ FFmpeg conversion failed.")
        return "Conversion failed", 500

    os.remove(downloaded)
    size_mb = os.path.getsize(mp3_file) / (1024 * 1024)
    logging.info(f"✅ Conversion complete: {mp3_file} ({size_mb:.2f} MB)")

    return send_file(mp3_file, as_attachment=True)


# =====================================================
# 🚀 Start server
# =====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)