import os
import time
import json
import subprocess
import logging
import threading
from flask import Flask, Response, request
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Interval settings
REFRESH_INTERVAL = 1200       # 20 minutes
RECHECK_INTERVAL = 3600       # 60 minutes
EXPIRE_AGE = 7200             # 2 hours

# Fixed user agent
FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

CHANNELS = {

"vallathorukatha": "https://www.youtube.com/@babu_ramachandran/videos",
    "furqan": "https://youtube.com/@alfurqan4991/videos",
    "skicr": "https://youtube.com/@skicrtv/videos",
    "dhruvrathee": "https://youtube.com/@dhruvrathee/videos",
    "safari": "https://youtube.com/@safaritvlive/videos",

"qasimi": "https://www.youtube.com/@quranstudycentremukkam/videos",
    "sharique": "https://youtube.com/@shariquesamsudheen/videos",


    "vijayakumarblathur": "https://youtube.com/@vijayakumarblathur/videos",
 "entridegree": "https://youtube.com/@entridegreelevelexams/videos",
     "talent": "https://youtube.com/@talentacademyonline/videos",

   "drali": "https://youtube.com/@draligomaa/videos",
    "yaqeen": "https://youtube.com/@yaqeeninstituteofficial/videos",
    "ccm": "https://youtube.com/@cambridgecentralmosque/videos",
    "maheen": "https://youtube.com/@hitchhikingnomaad/videos",
    "entri": "https://youtube.com/@entriapp/videos",
    "zamzam": "https://youtube.com/@zamzamacademy/videos",
    "jrstudio": "https://youtube.com/@jrstudiomalayalam/videos",
    "raftalks": "https://youtube.com/@raftalksmalayalam/videos",
    "parvinder": "https://www.youtube.com/@pravindersheoran/videos",


    "suprabhatam": "https://youtube.com/@suprabhaatham2023/videos",
    "bayyinah": "https://youtube.com/@bayyinah/videos",

    "sunnxt": "https://youtube.com/@sunnxtmalayalam/videos",
    "movieworld": "https://youtube.com/@movieworldmalayalammovies/videos",
    "comedy": "https://youtube.com/@malayalamcomedyscene5334/videos",
    "studyiq": "https://youtube.com/@studyiqiasenglish/videos",
    "sreekanth": "https://youtube.com/@sreekanthvettiyar/videos",
    "jr": "https://youtube.com/@yesitsmejr/videos",
    "habib": "https://youtube.com/@habibomarcom/videos",
    "unacademy": "https://youtube.com/@unacademyiasenglish/videos",
    "eftguru": "https://youtube.com/@eftguru-ql8dk/videos",
    "anurag": "https://youtube.com/@anuragtalks1/videos",
}

VIDEO_CACHE = {
    name: {"url": None, "last_checked": 0, "thumbnail": "", "upload_date": "", "title": "", "channel": ""}
    for name in CHANNELS
}
LAST_VIDEO_ID = {name: None for name in CHANNELS}
TMP_DIR = Path("/tmp/ytmp3")
TMP_DIR.mkdir(exist_ok=True)

def fetch_latest_video_url(name, channel_url):
    try:
        result = subprocess.run([
            "yt-dlp",
            "--dump-single-json",
            "--playlist-end", "1",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            channel_url
        ], capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)
        video = data["entries"][0]
        video_id = video["id"]
        thumbnail_url = video.get("thumbnail", "")
        upload_date = video.get("upload_date", "")
        title = video.get("title", "")
        channel = video.get("channel", "")
        return f"https://www.youtube.com/watch?v={video_id}", thumbnail_url, video_id, upload_date, title, channel
    except Exception as e:
        logging.error(f"Error fetching video from {channel_url}: {e}")
        return None, None, None, None, None, None

def format_upload_month(upload_date):
    try:
        dt = datetime.strptime(upload_date, "%Y%m%d")
        return dt.strftime("%B %Y")  # e.g., "April 2025"
    except Exception:
        return "Unknown"

def download_and_convert(channel, video_url):
    final_path = TMP_DIR / f"{channel}.mp3"
    if final_path.exists():
        return final_path
    if not video_url:
        return None

    try:
        base_path = TMP_DIR / channel
        audio_path = base_path.with_suffix(".webm")
        thumb_path = base_path.with_suffix(".jpg")

        # Download best audio and thumbnail
        subprocess.run([
            "yt-dlp",
            "-f", "bestaudio",
            "--output", str(base_path) + ".%(ext)s",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--cookies", "/mnt/data/cookies.txt",
            "--user-agent", FIXED_USER_AGENT,
            video_url
        ], check=True)

        if not audio_path.exists() or not thumb_path.exists():
            logging.error(f"Missing audio or thumbnail for {channel}")
            return None

        info = VIDEO_CACHE[channel]
        title = info.get("title", channel)
        artist = info.get("channel", channel)
        album = format_upload_month(info.get("upload_date", ""))

        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-i", str(thumb_path),
            "-map", "0:a",
            "-map", "1:v",
            "-c:a", "libmp3lame",
            "-c:v", "mjpeg",
            "-b:a", "64k",
            "-ar", "22050",
            "-ac", "1",
            "-id3v2_version", "3",
            "-metadata", f"title={title}",
            "-metadata", f"album={album}",
            "-metadata", f"artist={artist}",
            "-disposition:v", "attached_pic",
            str(final_path)
        ], check=True)

        audio_path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)

        return final_path if final_path.exists() else None
    except Exception as e:
        logging.error(f"Error converting {channel}: {e}")
        partial = final_path.with_suffix(".mp3.part")
        if partial.exists():
            partial.unlink()
        return None

def cleanup_old_files():
    while True:
        current_time = time.time()
        for file in TMP_DIR.glob("*.mp3"):
            if current_time - file.stat().st_mtime > EXPIRE_AGE:
                try:
                    logging.info(f"Cleaning up old file: {file}")
                    file.unlink()
                except Exception as e:
                    logging.error(f"Error cleaning up file {file}: {e}")
        time.sleep(EXPIRE_AGE)

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

def auto_download_mp3s():
    while True:
        for name, data in VIDEO_CACHE.items():
            video_url = data.get("url")
            if video_url:
                mp3_path = TMP_DIR / f"{name}.mp3"
                if not mp3_path.exists() or time.time() - mp3_path.stat().st_mtime > RECHECK_INTERVAL:
                    logging.info(f"Pre-downloading {name}")
                    download_and_convert(name, video_url)
            time.sleep(3)
        time.sleep(RECHECK_INTERVAL)

@app.route("/<channel>.mp3")
def stream_mp3(channel):
    if channel not in CHANNELS:
        return "Channel not found", 404

    data = VIDEO_CACHE[channel]
    video_url = data.get("url")
    if not video_url:
        video_url, thumbnail, video_id, upload_date, title, channel_name = fetch_latest_video_url(channel, CHANNELS[channel])
        if not video_url:
            return "Unable to fetch video", 500
        if video_id and LAST_VIDEO_ID[channel] != video_id:
            LAST_VIDEO_ID[channel] = video_id
            VIDEO_CACHE[channel].update({
                "url": video_url,
                "last_checked": time.time(),
                "thumbnail": thumbnail,
                "upload_date": upload_date,
                "title": title,
                "channel": channel_name,
            })

    mp3_path = download_and_convert(channel, video_url)
    if not mp3_path or not mp3_path.exists():
        return "Error preparing stream", 500

    file_size = os.path.getsize(mp3_path)
    range_header = request.headers.get('Range', None)
    headers = {
        'Content-Type': 'audio/mpeg',
        'Accept-Ranges': 'bytes',
    }

    if range_header:
        try:
            range_value = range_header.strip().split("=")[1]
            byte1, byte2 = range_value.split("-")
            byte1 = int(byte1)
            byte2 = int(byte2) if byte2 else file_size - 1
        except Exception as e:
            return f"Invalid Range header: {e}", 400

        length = byte2 - byte1 + 1
        with open(mp3_path, 'rb') as f:
            f.seek(byte1)
            chunk = f.read(length)

        headers.update({
            'Content-Range': f'bytes {byte1}-{byte2}/{file_size}',
            'Content-Length': str(length)
        })
        return Response(chunk, status=206, headers=headers)

    with open(mp3_path, 'rb') as f:
        data = f.read()
    headers['Content-Length'] = str(file_size)
    return Response(data, headers=headers)

@app.route("/")
def index():
    html = """
    <html>
    <head>
        <title>YouTube Mp3</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: sans-serif;
                font-size: 14px;
                background: #fff;
                margin: 0;
                padding: 10px;
            }
            h3 {
                text-align: center;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                gap: 10px;
            }
            .card {
                border: 1px solid #ccc;
                border-radius: 8px;
                padding: 6px;
                background: #f9f9f9;
            }
            .card img {
                width: 100%;
                height: auto;
                border-radius: 4px;
                margin-bottom: 4px;
            }
            .card a {
                color: #000;
                text-decoration: none;
                font-weight: bold;
            }
            .card small {
                color: #666;
            }
        </style>
    </head>
    <body>
        <h3>YouTube Mp3</h3>
        <div class="grid">
    """

    def get_upload_date(channel):
        return VIDEO_CACHE[channel].get("upload_date", "Unknown")

    for channel in sorted(CHANNELS, key=lambda x: get_upload_date(x), reverse=True):
        mp3_path = TMP_DIR / f"{channel}.mp3"
        if not mp3_path.exists():
            continue
        thumbnail = (VIDEO_CACHE[channel].get("thumbnail", "") or "http://via.placeholder.com/120x80?text=YT").replace("https://", "http://")
        upload_date = get_upload_date(channel)
        html += f"""
            <div class="card">
                <img src="{thumbnail}" loading="lazy" alt="{channel}">
                <div style="text-align:center;">
                    <a href="/{channel}.mp3">{channel}</a><br>
                    <small>{upload_date}</small>
                </div>
            </div>
        """

    html += """
        </div>
    </body>
    </html>
    """
    return html
threading.Thread(target=update_video_cache_loop, daemon=True).start()
threading.Thread(target=auto_download_mp3s, daemon=True).start()
threading.Thread(target=cleanup_old_files, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)