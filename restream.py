import os
import time
import json
import subprocess
import logging
import threading
from flask import Flask, Response, request, stream_with_context
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Settings
REFRESH_INTERVAL = 1200       # 20 mins
RECHECK_INTERVAL = 3600       # 1 hour
EXPIRE_AGE = 7200             # 2 hours
FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TMP_DIR = Path("/tmp/ytmp3")
TMP_DIR.mkdir(exist_ok=True)

# Channel list
CHANNELS = {
    "furqan": "https://youtube.com/@alfurqan4991/videos",
    "vallathorukatha": "https://www.youtube.com/@babu_ramachandran/videos",
    "suprabhatam": "https://youtube.com/@suprabhaatham2023/videos",
    # Add more as needed
}

VIDEO_CACHE = {
    name: {"url": None, "last_checked": 0, "thumbnail": "", "upload_date": "", "title": "", "channel": ""}
    for name in CHANNELS
}
LAST_VIDEO_ID = {name: None for name in CHANNELS}

# Fetch latest video
def fetch_latest_video_url(name, channel_url):
    try:
        result = subprocess.run([
            "yt-dlp", "--dump-single-json", "--playlist-end", "1",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            channel_url
        ], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        video = data["entries"][0]
        return (
            f"https://www.youtube.com/watch?v={video['id']}",
            video.get("thumbnail", ""),
            video["id"],
            video.get("upload_date", ""),
            video.get("title", ""),
            video.get("channel", "")
        )
    except Exception as e:
        logging.error(f"Error fetching video from {channel_url}: {e}")
        return (None, None, None, None, None, None)

# Convert upload date to month/year
def format_upload_month(upload_date):
    try:
        dt = datetime.strptime(upload_date, "%Y%m%d")
        return dt.strftime("%B %Y")
    except Exception:
        return "Unknown"

# Download and convert to mp3
def download_and_convert(channel, video_url):
    final_path = TMP_DIR / f"{channel}.mp3"
    if final_path.exists():
        return final_path
    try:
        base_path = TMP_DIR / channel
        audio_path = base_path.with_suffix(".webm")
        thumb_path = base_path.with_suffix(".jpg")

        subprocess.run([
            "yt-dlp", "-f", "bestaudio",
            "--output", str(base_path) + ".%(ext)s",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            video_url
        ], check=True)

        info = VIDEO_CACHE[channel]
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-i", str(thumb_path),
            "-map", "0:a", "-map", "1:v",
            "-c:a", "libmp3lame", "-c:v", "mjpeg",
            "-b:a", "64k", "-ar", "22050", "-ac", "1",
            "-id3v2_version", "3",
            "-metadata", f"title={info.get('title', channel)}",
            "-metadata", f"album={format_upload_month(info.get('upload_date', ''))}",
            "-metadata", f"artist={info.get('channel', channel)}",
            "-disposition:v", "attached_pic",
            str(final_path)
        ], check=True)

        audio_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        return final_path
    except Exception as e:
        logging.error(f"Error converting {channel}: {e}")
        return None

# Periodic update
def update_video_cache_loop():
    while True:
        for name, url in CHANNELS.items():
            video_url, thumbnail, video_id, upload_date, title, channel_name = fetch_latest_video_url(name, url)
            if video_url and video_id:
                if LAST_VIDEO_ID[name] != video_id:
                    LAST_VIDEO_ID[name] = video_id
                    VIDEO_CACHE[name].update({
                        "url": video_url,
                        "last_checked": time.time(),
                        "thumbnail": thumbnail,
                        "upload_date": upload_date,
                        "title": title,
                        "channel": channel_name,
                    })
                    download_and_convert(name, video_url)
            time.sleep(3)
        time.sleep(REFRESH_INTERVAL)

# Periodic redownload
def auto_download_mp3s():
    while True:
        for name, data in VIDEO_CACHE.items():
            video_url = data.get("url")
            if video_url:
                mp3_path = TMP_DIR / f"{name}.mp3"
                if not mp3_path.exists() or time.time() - mp3_path.stat().st_mtime > RECHECK_INTERVAL:
                    download_and_convert(name, video_url)
            time.sleep(3)
        time.sleep(RECHECK_INTERVAL)

# Cleanup old files
def cleanup_old_files():
    while True:
        now = time.time()
        for file in TMP_DIR.glob("*.mp3"):
            if now - file.stat().st_mtime > EXPIRE_AGE:
                try:
                    file.unlink()
                except Exception as e:
                    logging.error(f"Cleanup error: {e}")
        time.sleep(EXPIRE_AGE)

# Cached download stream
@app.route("/<channel>.mp3")
def stream_mp3(channel):
    if channel not in CHANNELS:
        return "Channel not found", 404
    data = VIDEO_CACHE[channel]
    video_url = data.get("url")
    if not video_url:
        video_url, *_ = fetch_latest_video_url(channel, CHANNELS[channel])
        if not video_url:
            return "No video", 500
    mp3_path = download_and_convert(channel, video_url)
    if not mp3_path or not mp3_path.exists():
        return "Failed", 500

    size = os.path.getsize(mp3_path)
    headers = {'Content-Type': 'audio/mpeg', 'Accept-Ranges': 'bytes'}
    range_header = request.headers.get("Range", None)

    if range_header:
        try:
            start, end = range_header.replace("bytes=", "").split("-")
            start = int(start)
            end = int(end) if end else size - 1
            length = end - start + 1
            with open(mp3_path, "rb") as f:
                f.seek(start)
                data = f.read(length)
            headers.update({
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(length)
            })
            return Response(data, 206, headers)
        except:
            return "Invalid range", 400

    with open(mp3_path, "rb") as f:
        return Response(f.read(), headers | {"Content-Length": str(size)})

# Real-time stream
@app.route("/live/<channel>.mp3")
def stream_realtime_mp3(channel):
    if channel not in CHANNELS:
        return "Channel not found", 404

    video_url, *_ = fetch_latest_video_url(channel, CHANNELS[channel])
    if not video_url:
        return "Unable to get video", 500

    try:
        result = subprocess.run([
            "yt-dlp", "-f", "bestaudio", "-g",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            video_url
        ], capture_output=True, text=True, check=True)
        audio_url = result.stdout.strip()
    except Exception as e:
        return f"Error fetching audio URL: {e}", 500

    def generate():
        ffmpeg = subprocess.Popen([
            "ffmpeg", "-i", audio_url,
            "-vn", "-f", "mp3", "-b:a", "96k", "-ac", "1", "-ar", "22050",
            "-loglevel", "quiet", "-"
        ], stdout=subprocess.PIPE)
        try:
            while True:
                chunk = ffmpeg.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            ffmpeg.kill()

    return Response(stream_with_context(generate()), {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-store"
    })

# Web UI
@app.route("/")
def index():
    html = """
    <html><head><title>YouTube MP3</title>
    <meta name="viewport" content="width=device-width">
    <style>
    body { font-family:sans-serif; padding:10px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; }
    .card { background:#f9f9f9; border:1px solid #ccc; border-radius:8px; padding:6px; text-align:center; }
    img { width:100%; border-radius:4px; }
    </style></head><body>
    <h3>YouTube MP3</h3><div class="grid">
    """
    for ch in sorted(CHANNELS, key=lambda x: VIDEO_CACHE[x].get("upload_date", ""), reverse=True):
        thumb = VIDEO_CACHE[ch].get("thumbnail") or "http://via.placeholder.com/120x80?text=YT"
        html += f"""
        <div class='card'>
            <img src='{thumb}' alt='{ch}'>
            <a href='/{ch}.mp3'>{ch}</a> |
            <a href='/live/{ch}.mp3' style='color:green'>Live</a>
        </div>
        """
    html += "</div></body></html>"
    return html

# Background threads
threading.Thread(target=update_video_cache_loop, daemon=True).start()
threading.Thread(target=auto_download_mp3s, daemon=True).start()
threading.Thread(target=cleanup_old_files, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)