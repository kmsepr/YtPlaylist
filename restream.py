import os, time, json, threading, subprocess, logging, requests
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context
from logging.handlers import RotatingFileHandler

# ---------------- CONFIG ----------------
LOG_PATH = "/mnt/data/radio_tv.log"
COOKIES_FILE = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/cache.json"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=512000, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), handler]
)
app = Flask(__name__)

# ---------------- TV STREAMS ----------------
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

# ---------------- YouTube LIVE STREAMS ----------------
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
    **{k: "https://upload.wikimedia.org/wikipedia/commons/b/b8/YouTube_Logo_2017.svg" for k in YOUTUBE_STREAMS},
}

CACHE, LIVE_STATUS = {}, {}

# ---------------- YOUTUBE LIVE REFRESH ----------------
def get_youtube_live_url(url):
    try:
        cmd = ["yt-dlp", "-f", "best[height<=360]", "-g", url]
        if os.path.exists(COOKIES_FILE):
            cmd.insert(1, "--cookies")
            cmd.insert(2, COOKIES_FILE)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None

def refresh_stream_urls():
    while True:
        logging.info("🔄 Refreshing YouTube live URLs...")
        for name, url in YOUTUBE_STREAMS.items():
            live_url = get_youtube_live_url(url)
            if live_url:
                CACHE[name] = live_url
                LIVE_STATUS[name] = True
            else:
                LIVE_STATUS[name] = False
        time.sleep(120)

threading.Thread(target=refresh_stream_urls, daemon=True).start()

# ---------------- YOUTUBE RADIO ----------------
PLAYLISTS = {"kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ"}
STREAMS = {}
REFRESH_INTERVAL = 1800
MAX_QUEUE = 128

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE))
        except:
            return {}
    return {}

def save_cache(data):
    try:
        json.dump(data, open(CACHE_FILE, "w"))
    except Exception as e:
        logging.error(e)

CACHE_PLAYLIST = load_cache()

def load_playlist_ids(name, force=False):
    now = time.time()
    cached = CACHE_PLAYLIST.get(name, {})
    if not force and cached and now - cached.get("time", 0) < REFRESH_INTERVAL:
        return cached["ids"]
    url = PLAYLISTS[name]
    try:
        res = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url, "--cookies", COOKIES_FILE],
            capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        ids = [e["id"] for e in data.get("entries", []) if "id" in e][::-1]  # latest first
        CACHE_PLAYLIST[name] = {"ids": ids, "time": now}
        save_cache(CACHE_PLAYLIST)
        logging.info(f"[{name}] Cached {len(ids)} videos.")
        return ids
    except Exception as e:
        logging.error(f"[{name}] Playlist error: {e}")
        return cached.get("ids", [])

def stream_worker(name):
    s = STREAMS[name]
    while True:
        try:
            ids = s["IDS"]
            if not ids:
                ids = load_playlist_ids(name, True)
                s["IDS"] = ids
            vid = ids[s["INDEX"] % len(ids)]
            s["INDEX"] += 1
            url = f"https://www.youtube.com/watch?v={vid}"
            logging.info(f"[{name}] ▶️ {url}")
            cmd = (
                f'yt-dlp -f "bestaudio/best" --cookies "{COOKIES_FILE}" '
                f'-o - --quiet --no-warnings "{url}" | '
                f'ffmpeg -loglevel quiet -i pipe:0 -ac 1 -ar 44100 -b:a 40k '
                f'-f mp3 -content_type audio/mpeg pipe:1'
            )
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                if len(s["QUEUE"]) < MAX_QUEUE:
                    s["QUEUE"].append(chunk)
            proc.stdout.close()
            proc.wait()
        except Exception as e:
            logging.error(e)
            time.sleep(5)

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return render_template_string("""
<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>📡 Live & Radio</title>
<style>
body{background:#000;color:#0f0;text-align:center;font-family:sans-serif}
a{display:block;color:#0f0;border:1px solid #0f0;margin:10px;padding:10px;border-radius:10px;text-decoration:none}
</style></head><body>
<h2>📺 Live TV & ▶️ YouTube Radio</h2>
<a href="/channels">🎬 TV + YouTube Live</a>
{% for n in playlists %}
<a href="/listen/{{n}}">🎧 {{n|capitalize}} Radio</a>
{% endfor %}
</body></html>""", playlists=PLAYLISTS.keys())

@app.route("/channels")
def tv_home():
    live_youtube = [n for n, live in LIVE_STATUS.items() if live]
    html = "<h2 style='text-align:center;color:#0f0;'>📺 Channels</h2><ul>"
    for k in list(TV_STREAMS.keys()) + live_youtube:
        html += f"<li><a href='/watch/{k}'>{k}</a></li>"
    html += "</ul><a href='/'>⬅ Back</a>"
    return html

@app.route("/listen/<name>")
def listen(name):
    if name not in PLAYLISTS: abort(404)
    return f"""<html><body style='background:#000;color:#0f0;text-align:center'>
<h2>{name} Radio</h2>
<audio controls autoplay style='width:90%'><source src='/stream/{name}' type='audio/mpeg'></audio>
<p>🎵 Latest YouTube Playlist Stream</p></body></html>"""

@app.route("/stream/<name>")
def stream_audio(name):
    if name in STREAMS:
        s = STREAMS[name]
        def gen():
            while True:
                if s["QUEUE"]:
                    yield s["QUEUE"].popleft()
                else:
                    time.sleep(0.05)
        return Response(stream_with_context(gen()), mimetype="audio/mpeg")
    elif name in CACHE:
        return Response(requests.get(CACHE[name]).content, mimetype="application/vnd.apple.mpegurl")
    abort(404)

@app.route("/watch/<channel>")
def watch(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return "Stream not ready", 503
    return f"""<html><body style='background:#000;color:#0f0;text-align:center'>
<h2>{channel}</h2>
<video src='{url}' controls autoplay style='width:90%;max-width:720px;'></video>
<p><a href='/'>⬅ Back</a></p></body></html>"""

# ---------------- MAIN ----------------
if __name__ == "__main__":
    for pname in PLAYLISTS:
        STREAMS[pname] = {"IDS": load_playlist_ids(pname), "INDEX": 0, "QUEUE": deque()}
        threading.Thread(target=stream_worker, args=(pname,), daemon=True).start()
    logging.info("🚀 Combined TV + YouTube Radio started")
    app.run(host="0.0.0.0", port=8000)