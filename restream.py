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

@app.route("/audio/<channel>")
def audio_only(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return f"Channel '{channel}' not ready or offline", 503
    logging.info(f"🎧 Streaming audio for {channel} ({url[:50]}...)")
    def generate():
        cmd = ["ffmpeg", "-i", url, "-vn", "-ac", "1", "-b:a", "48k", "-f", "mp3", "pipe:1"]
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
# 🎶 YouTube Radio SECTION (queue-based)
# ==============================================================

LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = COOKIES_FILE
CACHE_FILE = "/mnt/data/playlist_cache.json"
os.makedirs(DOWNLOAD_DIR := "/mnt/data/radio_cache", exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.getLogger().addHandler(handler)

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
}

STREAMS_RADIO = {}
MAX_QUEUE = 128
REFRESH_INTERVAL = 1800  # 30 min

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
<p>Now streaming low-bitrate MP3 (mono, 40 kbps)</p>
<a href="/radio">⬅ Back</a></body></html>"""

def load_cache_radio():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE))
        except Exception:
            return {}
    return {}

def save_cache_radio(data):
    try:
        json.dump(data, open(CACHE_FILE, "w"))
    except Exception as e:
        logging.error(e)

CACHE_RADIO = load_cache_radio()

def load_playlist_ids_radio(name, force=False):
    now = time.time()
    cached = CACHE_RADIO.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]

    url = PLAYLISTS[name]
    try:
        logging.info(f"[{name}] Refreshing playlist...")
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_PATH],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if "id" in e][::-1]
        CACHE_RADIO[name] = {"ids": ids, "time": now}
        save_cache_radio(CACHE_RADIO)
        logging.info(f"[{name}] Cached {len(ids)} videos.")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

def stream_worker_radio(name):
    s = STREAMS_RADIO[name]
    while True:
        try:
            ids = s["IDS"]
            if not ids:
                ids = load_playlist_ids_radio(name, True)
                s["IDS"] = ids
            if not ids:
                logging.warning(f"[{name}] No playlist ids found; sleeping...")
                time.sleep(10)
                continue
            vid = ids[s["INDEX"] % len(ids)]
            s["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ {url}")

            cmd = (
                f'yt-dlp -f "bestaudio/best" --cookies "{COOKIES_PATH}" '
                f'--user-agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" '
                f'-o - --quiet --no-warnings "{url}" | '
                f'ffmpeg -loglevel quiet -i pipe:0 -ac 1 -ar 44100 -b:a 40k -f mp3 pipe:1'
            )
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(s["QUEUE"]) < MAX_QUEUE:
                    s["QUEUE"].append(chunk)

            proc.stdout.close()
            proc.wait()
            logging.info(f"[{name}] ✅ Finished one track.")
        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(5)

# ---------------- ROUTES ----------------
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
    if name not in STREAMS_RADIO:
        abort(404)
    s = STREAMS_RADIO[name]

    def gen():
        while True:
            if s["QUEUE"]:
                yield s["QUEUE"].popleft()
            else:
                time.sleep(0.05)

    return Response(stream_with_context(gen()), mimetype="audio/mpeg")

# ==============================================================
# 🚀 START SERVER
# ==============================================================

if __name__ == "__main__":
    # Initialize radio streams
    for pname in PLAYLISTS:
        STREAMS_RADIO[pname] = {
            "IDS": load_playlist_ids_radio(pname),
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker_radio, args=(pname,), daemon=True).start()

    logging.info("🚀 Live TV + YouTube + Radio server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)