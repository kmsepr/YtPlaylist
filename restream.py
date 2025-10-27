import os, time, json, threading, subprocess, logging, requests
from flask import Flask, Response, render_template_string, abort, stream_with_context
from logging.handlers import RotatingFileHandler
from collections import deque

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

# ==============================================================
# 📺 TV + YouTube Live SECTION (original)
# ==============================================================

TV_STREAMS = {
    "safari_tv": "https://j78dp346yq5r-hls-live.5centscdn.com/safari/live.stream/chunks.m3u8",
    "dd_sports": "https://cdn-6.pishow.tv/live/13/master.m3u8",
    "dd_malayalam": "https://d3eyhgoylams0m.cloudfront.net/v1/manifest/93ce20f0f52760bf38be911ff4c91ed02aa2fd92/ed7bd2c7-8d10-4051-b397-2f6b90f99acb/562ee8f9-9950-48a0-ba1d-effa00cf0478/2.m3u8",
    "mazhavil_manorama": "https://yuppmedtaorire.akamaized.net/v1/master/a0d007312bfd99c47f76b77ae26b1ccdaae76cb1/mazhavilmanorama_nim_https/050522/mazhavilmanorama/playlist.m3u8",
    "victers_tv": "https://932y4x26ljv8-hls-live.5centscdn.com/victers/tv.stream/chunks.m3u8",
    "france_24": "https://live.france24.com/hls/live/2037218/F24_EN_HI_HLS/master_500.m3u8",
    "mult": "http://stv.mediacdn.ru/live/cdn/mult/playlist.m3u8",
    "star_sports": "http://87.255.35.150:18828/",
}

YOUTUBE_STREAMS = {
    "asianet_news": "https://www.youtube.com/@asianetnews/live",
    "media_one": "https://www.youtube.com/@MediaoneTVLive/live",
    "shajahan_rahmani": "https://www.youtube.com/@ShajahanRahmaniOfficial/live",
    "qsc_mukkam": "https://www.youtube.com/c/quranstudycentremukkam/live",
    "valiyudheen_faizy": "https://www.youtube.com/@voiceofvaliyudheenfaizy600/live",
    "skicr_tv": "https://www.youtube.com/@SKICRTV/live",
    "yaqeen_institute": "https://www.youtube.com/@yaqeeninstituteofficial/live",
    "bayyinah_tv": "https://www.youtube.com/@bayyinah/live",
    "eft_guru": "https://www.youtube.com/@EFTGuru-ql8dk/live",
    "unacademy_ias": "https://www.youtube.com/@UnacademyIASEnglish/live",
    "studyiq_hindi": "https://www.youtube.com/@StudyIQEducationLtd/live",
    "aljazeera_arabic": "https://www.youtube.com/@aljazeera/live",
    "aljazeera_english": "https://www.youtube.com/@AlJazeeraEnglish/live",
    "entri_degree": "https://www.youtube.com/@EntriDegreeLevelExams/live",
    "xylem_psc": "https://www.youtube.com/@XylemPSC/live",
    "xylem_sslc": "https://www.youtube.com/@XylemSSLC2023/live",
    "entri_app": "https://www.youtube.com/@entriapp/live",
    "entri_ias": "https://www.youtube.com/@EntriIAS/live",
    "studyiq_english": "https://www.youtube.com/@studyiqiasenglish/live",
    "voice_rahmani": "https://www.youtube.com/@voiceofrahmaniyya5828/live",
    "kas_ranker": "https://www.youtube.com/@freepscclasses/live",
    "suprabhatam": "https://www.youtube.com/@suprabhaatham_online/live",
}

CHANNEL_LOGOS = {
    "star_sports": "https://imgur.com/5En7pOI.png",
    "safari_tv": "https://i.imgur.com/dSOfYyh.png",
    "victers_tv": "https://i.imgur.com/kj4OEsb.png",
    "france_24": "https://upload.wikimedia.org/wikipedia/commons/c/c1/France_24_logo_%282013%29.svg",
    "mazhavil_manorama": "https://i.imgur.com/fjgzW20.png",
    "dd_malayalam": "https://i.imgur.com/ywm2dTl.png",
    "dd_sports": "https://i.imgur.com/J2Ky5OO.png",
    "mult": "https://i.imgur.com/xi351Fx.png",
    **{k: "https://upload.wikimedia.org/wikipedia/commons/b/b8/YouTube_Logo_2017.svg" for k in YOUTUBE_STREAMS}
}

CACHE = {}
LIVE_STATUS = {}
COOKIES_FILE = "/mnt/data/cookies.txt"

def get_youtube_live_url(youtube_url: str):
    try:
        cmd = ["yt-dlp", "-f", "best[height<=360]", "-g", youtube_url]
        if os.path.exists(COOKIES_FILE):
            cmd.insert(1, "--cookies")
            cmd.insert(2, COOKIES_FILE)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logging.warning(f"yt-dlp error for {youtube_url}: {e}")
    return None

def refresh_stream_urls():
    while True:
        logging.info("🔄 Refreshing YouTube live URLs...")
        for name, url in YOUTUBE_STREAMS.items():
            direct_url = get_youtube_live_url(url)
            if direct_url:
                CACHE[name] = direct_url
                LIVE_STATUS[name] = True
            else:
                LIVE_STATUS[name] = False
        time.sleep(90)

threading.Thread(target=refresh_stream_urls, daemon=True).start()

@app.route("/")
def home():
    tv_channels = list(TV_STREAMS.keys())
    youtube_live = [n for n, live in LIVE_STATUS.items() if live]
    html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>📺 Live TV & YouTube</title>
<style>
body{background:#000;color:#fff;font-family:sans-serif;text-align:center;margin:0}
h1{color:#0ff;margin:15px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:15px;padding:15px}
.card{background:#111;border-radius:12px;padding:8px;transition:0.3s}
.card:hover{transform:scale(1.05);background:#0ff;color:#000}
.card img{width:100%;height:100px;object-fit:contain;border-radius:10px;background:#000}
a{color:#0ff;text-decoration:none;margin:4px;display:inline-block}
a:hover{color:#ff0}
</style></head><body>
<h1>📡 Live Channels</h1>
<h2>TV Channels</h2>
<div class="grid">
{% for c in tv_channels %}
<div class="card">
<img src="{{ logos.get(c) }}"><b>{{ c.replace('_',' ').title() }}</b><br>
<a href="/watch/{{ c }}">▶ Watch</a>
<a href="/audio/{{ c }}">🎵 Audio</a>
</div>{% endfor %}</div>
<h2>YouTube Live</h2>
<div class="grid">
{% for c in youtube_channels %}
<div class="card">
<img src="{{ logos.get(c) }}"><b>{{ c.replace('_',' ').title() }}</b><br>
<a href="/watch/{{ c }}">▶ Watch</a>
<a href="/audio/{{ c }}">🎵 Audio</a>
</div>{% endfor %}</div>
<h2>🎧 YouTube Radio</h2>
<a href="/radio" style="color:#0ff;border:1px solid #0ff;padding:10px;border-radius:8px;display:inline-block">🎶 Open Radio</a>
</body></html>"""
    return render_template_string(html, tv_channels=tv_channels, youtube_channels=youtube_live, logos=CHANNEL_LOGOS)

@app.route("/watch/<channel>")
def watch(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return "Channel not available", 503
    return f"""<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<script src='https://cdn.jsdelivr.net/npm/hls.js@latest'></script>
<style>body{{background:#000;color:#fff;text-align:center}}video{{width:95%;max-width:720px}}</style></head>
<body><h2>{channel.replace('_',' ').title()}</h2>
<video id='v' controls autoplay playsinline></video>
<script>if(Hls.isSupported()){{let h=new Hls();h.loadSource("{url}");h.attachMedia(document.getElementById('v'));}}
else{{document.getElementById('v').src="{url}";}}</script>
<a href='/'>⬅ Home</a></body></html>"""


       # -----------------------
# Unified Audio Route (TV + YouTube) with Player + Download Button
# -----------------------
@app.route("/audio/<channel>")
def audio_only(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return f"Channel '{channel}' not ready or offline", 503

    # Audio stream route
    stream_url = f"/stream/{channel}"

    html = f"""
    <html>
    <head>
    <meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>{channel.replace('_',' ').title()} - Audio</title>
    <style>
    body{{background:#000;color:#fff;text-align:center;font-family:sans-serif;margin:0;padding:0}}
    h2{{color:#0ff;margin-top:20px}}
    audio{{width:90%;margin-top:20px}}
    a,button{{color:#000;background:#0ff;border:none;padding:10px 20px;
              border-radius:8px;text-decoration:none;display:inline-block;margin:15px}}
    a:hover,button:hover{{background:#ff0;color:#000}}
    </style>
    </head>
    <body>
    <h2>🎧 {channel.replace('_',' ').title()}</h2>
    <audio controls autoplay>
        <source src="{stream_url}" type="audio/mpeg">
        Your browser does not support the audio element.
    </audio>
    <br>
    <a href="{stream_url}" download="{channel}.mp3">⬇ Download</a>
    <br>
    <a href="/">⬅ Home</a>
    </body>
    </html>
    """
    return html

# -----------------------
# Direct Stream Route for Downloading
# -----------------------
@app.route("/stream/<channel>")
def stream_audio(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return f"Channel '{channel}' not ready or offline", 503

    logging.info(f"🎧 Streaming audio for {channel} ({url[:50]}...)")

    def generate():
        cmd = [
            "ffmpeg", "-i", url,
            "-vn", "-ac", "1", "-b:a", "48k", "-f", "mp3", "pipe:1"
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                chunk = proc.stdout.read(1024)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.terminate()

    return Response(generate(), mimetype="audio/mpeg")


# ==============================================================
# 🎶 YouTube Radio SECTION (added)
# ==============================================================

LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = COOKIES_FILE
CACHE_FILE = "/mnt/data/playlist_cache.json"
DOWNLOAD_DIR = "/mnt/data/radio_cache"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.getLogger().addHandler(handler)

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
}

STREAMS = {}
REFRESH_INTERVAL = 1800
DOWNLOAD_INTERVAL = 3600

RADIO_HOME_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>YouTube Radio</title><style>
body{background:#000;color:#0f0;text-align:center;font-family:sans-serif}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:10px;display:block;border-radius:8px}
</style></head><body>
<h2>🎧 YouTube Radio</h2>
{% for n in playlists %}<a href="/listen/{{n}}">▶️ {{n|capitalize}}</a>{% endfor %}
<a href="/">⬅ Back to Live TV</a></body></html>"""

PLAYER_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{name|capitalize}}</title></head>
<body style="background:#000;color:#0f0;text-align:center;font-family:sans-serif">
<h3>🎶 {{name|capitalize}} Radio</h3>
<audio controls autoplay style="width:90%;margin-top:20px">
<source src="/stream/{{name}}" type="audio/mpeg"></audio>
<p>Now playing cached MP3 (updates hourly)</p>
<a href="/radio">⬅ Back</a></body></html>"""

def load_cache():
    if os.path.exists(CACHE_FILE):
        try: return json.load(open(CACHE_FILE))
        except Exception: return {}
    return {}

def save_cache(data):
    try: json.dump(data, open(CACHE_FILE, "w"))
    except Exception as e: logging.error(e)

CACHE_RADIO = load_cache()

def load_playlist_ids(name, force=False):
    now = time.time()
    cached = CACHE_RADIO.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]
    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist...")
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if "id" in e]
        ids.reverse()
        CACHE_RADIO[name] = {"ids": ids, "time": now}
        save_cache(CACHE_RADIO)
        logging.info(f"[{name}] Cached {len(ids)} videos (latest first).")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

def stream_worker(name):
    stream = STREAMS[name]
    while True:
        try:
            ids = stream["IDS"]
            if not ids:
                ids = load_playlist_ids(name, True)
                stream["IDS"] = ids
            if not ids:
                time.sleep(60); continue
            vid = ids[stream["INDEX"] % len(ids)]
            stream["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            outfile = os.path.join(DOWNLOAD_DIR, f"{name}.mp3")
            logging.info(f"[{name}] ⬇️ Downloading new track: {url}")
            subprocess.run([
                "yt-dlp", "-f", "bestaudio/best", "--cookies", COOKIES_PATH,
                "--extract-audio", "--audio-format", "mp3", "-o", outfile, url
            ], check=True)
            logging.info(f"[{name}] ✅ Track downloaded to {outfile}")
            stream["CURRENT_FILE"] = outfile
            stream["LAST_REFRESH"] = time.time()
            for _ in range(int(DOWNLOAD_INTERVAL / 10)):
                time.sleep(10)
                if time.time() - CACHE_RADIO.get(name, {}).get("time", 0) > REFRESH_INTERVAL:
                    load_playlist_ids(name, True)
        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(30)

@app.route("/radio")
def radio_home():
    return render_template_string(RADIO_HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/listen/<name>")
def listen_radio(name):
    if name not in PLAYLISTS:
        abort(404)
    return render_template_string(PLAYER_HTML, name=name)

@app.route("/stream/<name>")
def stream_audio(name):
    if name not in STREAMS:
        abort(404)

    path = STREAMS[name].get("CURRENT_FILE")
    if not path or not os.path.exists(path):
        # Not ready yet
        return Response(
            "Radio stream not ready — please wait a minute for initial caching.",
            status=503,
            mimetype="text/plain"
        )

    def generate():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                yield chunk

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")


# ==============================================================
# 🚀 START SERVER
# ==============================================================

if __name__ == "__main__":
    for name in PLAYLISTS:
        STREAMS[name] = {"IDS": load_playlist_ids(name), "INDEX": 0, "CURRENT_FILE": None, "LAST_REFRESH": 0}
        threading.Thread(target=stream_worker, args=(name,), daemon=True).start()
    logging.info("🚀 Live TV + YouTube + Radio server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)
