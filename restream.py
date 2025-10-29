import os
import time
import json
import threading
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

# ==============================================================
# 📺 TV + YouTube Live SECTION
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
    "kas_ranker": "https://youtube.com/@kasrankerofficial/live",
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

# start YouTube live refresh thread (kept intact)
threading.Thread(target=refresh_stream_urls, daemon=True).start()

# ==============================================================
# 🎶 YouTube Radio SECTION (Playlist-based)
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
    "ca": "https://youtube.com/playlist?list=PLYKzjRvMAyci_W5xYyIXHBoR63eefUadL",
    "studyiq": "https://youtube.com/playlist?list=PLMDetQy00TVmlsN2dnS_ybPdmAf02m9Y8",
    "hindi": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
    "samastha": "https://youtube.com/playlist?list=PLgkREi1Wpr-XgNxocxs3iPj61pqMhi9bv",
}

STREAMS_RADIO = {}
MAX_QUEUE = 128
REFRESH_INTERVAL = 1800  # 30 min

RADIO_HOME_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>YouTube Radio</title><style>
body{background:#000;color:#0f0;text-align:center;font-family:Arial,Helvetica,sans-serif;margin:0;padding:12px}
a{color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:10px;display:block;border-radius:8px}
</style></head><body>
<h2 style="font-size:18px;margin:6px 0">🎧 YouTube Radio</h2>
{% for n in playlists %}
  <a href="/listen/{{n}}" style="font-size:18px;padding:12px 8px">▶️ {{n|capitalize}}</a>
{% endfor %}
<a href="/" style="color:#0ff;border:1px solid #0ff;padding:10px;border-radius:8px;display:inline-block;margin-top:6px">⬅ Back</a>
</body></html>"""

PLAYER_HTML = """<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{name|capitalize}}</title></head>
<body style="background:#000;color:#0f0;text-align:center;font-family:Arial,Helvetica,sans-serif">
<h3 style="font-size:18px;margin-top:12px">🎶 {{name|capitalize}} Radio</h3>
<audio controls autoplay style="width:90%;margin-top:16px">
<source src="/stream/{{name}}" type="audio/mpeg"></audio>
<p style="font-size:14px;margin-top:10px">Now streaming low-bitrate MP3 (mono, 40 kbps)</p>
<a href="/#radio" style="color:#0ff;border:1px solid #0ff;padding:8px;border-radius:8px;display:inline-block;margin-top:8px">⬅ Back</a>
</body></html>"""

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

@app.route("/radio")
def radio_home():
    return render_template_string(RADIO_HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/listen/<name>")
def listen_radio_download(name):
    if name not in STREAMS_RADIO:
        abort(404)
    s = STREAMS_RADIO[name]

    def gen():
        while True:
            if s["QUEUE"]:
                yield s["QUEUE"].popleft()
            else:
                time.sleep(0.05)
    headers = {"Content-Disposition": f"attachment; filename={name}.mp3"}
    return Response(stream_with_context(gen()), mimetype="audio/mpeg", headers=headers)

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
# Home (single route) with two tabs (TV + Radio) — keypad friendly
# ==============================================================

HOME_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📺 TV & 🎵 Radio</title>
<style>
:root{
  --bg:#000;
  --card:#0b0b0b;
  --accent:#00ffff;
  --accent-2:#87cefa;
  --text:#ffffff;
  --muted:#9ae6ff;
}
html,body{background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif;margin:0;padding:8px}
.topbar{display:flex;gap:6px;justify-content:space-between;align-items:center;margin-bottom:8px}
.tabbtn{flex:1;padding:10px 6px;border-radius:8px;border:2px solid var(--accent);background:transparent;color:var(--accent);font-size:16px;text-align:center;font-weight:bold}
.tabbtn.inactive{border-color:#222;color:#666}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.card{background:var(--card);padding:8px;border-radius:10px;text-align:center;min-height:110px;box-shadow:0 0 6px rgba(0,0,0,0.6)}
.card img{width:100%;height:56px;object-fit:contain;border-radius:8px;background:#000;padding:4px}
.chn{font-size:14px;margin-top:6px;font-weight:bold;color:var(--muted)}
.links{margin-top:8px;display:flex;gap:6px;justify-content:center;align-items:center;flex-wrap:wrap}
.play-link, .audio-link{
  display:inline-block;padding:8px 10px;border-radius:8px;font-weight:bold;text-decoration:none;
  font-size:14px;
}
.play-link{background:var(--accent);color:#000}
.audio-link{background:transparent;color:var(--accent-2);border:2px solid var(--accent-2)}
.play-link:active, .audio-link:active{transform:scale(0.98)}
.small-note{font-size:12px;color:#9aa}
.header{font-size:18px;text-align:center;margin-bottom:6px;color:var(--accent)}
/* make big tappable area for keypad phones */
@media (max-width:360px){
  .tabbtn{font-size:15px;padding:12px}
  .card{min-height:120px}
  .play-link, .audio-link{padding:10px 12px;font-size:15px}
  .chn{font-size:15px}
}
</style>
</head>
<body>
<div class="topbar" role="tablist">
  <button id="tabTV" class="tabbtn" onclick="showTab('tv')">📺 TV</button>
  <button id="tabRadio" class="tabbtn inactive" onclick="showTab('radio')">🎵 Radio</button>
</div>

<div id="tv" class="tab" style="display:block">
  <div class="header">📡 Live TV Channels</div>
  <div class="grid">
  {% for c in tv_channels %}
    <div class="card" role="article">
      <img src="{{ logos.get(c) }}" alt="{{ c }}">
      <div class="chn">{{ c.replace('_',' ').title() }}</div>
      <div class="links">
        <a class="play-link" href="/watch/{{ c }}">▶ Watch</a>
        <a class="audio-link" href="/audio/{{ c }}">🎵 Audio</a>
      </div>
    </div>
  {% endfor %}
  </div>
  <div style="height:10px"></div>
  <div style="text-align:center">
    <a href="#radio" onclick="showTab('radio')" style="color:var(--accent);font-weight:bold">Open Radio ▶</a>
  </div>
</div>

<div id="radio" class="tab" style="display:none">
  <div class="header">🎧 YouTube Playlist Radio</div>
  <div style="padding:6px">
    {% for p in playlists %}
      <a href="/listen/{{p}}" class="play-link" style="display:block;margin-bottom:8px;text-align:center">▶ {{ p|capitalize }}</a>
    {% endfor %}
  </div>
  <div style="text-align:center;margin-top:6px">
    <a href="#" onclick="showTab('tv')" style="color:var(--accent);font-weight:bold">Back to TV ◀</a>
  </div>
</div>

<script>
function showTab(name){
  var tv = document.getElementById('tv');
  var radio = document.getElementById('radio');
  var tbtn = document.getElementById('tabTV');
  var rbtn = document.getElementById('tabRadio');
  if(name==='tv'){
    tv.style.display='block';
    radio.style.display='none';
    tbtn.classList.remove('inactive');
    rbtn.classList.add('inactive');
    window.location.hash = ''; // clean hash
  } else {
    tv.style.display='none';
    radio.style.display='block';
    tbtn.classList.add('inactive');
    rbtn.classList.remove('inactive');
    window.location.hash = 'radio';
  }
}
// open tab if hash present
if(window.location.hash === '#radio') showTab('radio');
</script>
</body>
</html>
"""

@app.route("/")
def home():
    tv_channels = list(TV_STREAMS.keys())
    playlists = list(PLAYLISTS.keys())
    return render_template_string(HOME_HTML, tv_channels=tv_channels, playlists=playlists, logos=CHANNEL_LOGOS)

@app.route("/watch/<channel>")
def watch(channel):
    url = TV_STREAMS.get(channel) or CACHE.get(channel)
    if not url:
        return "Channel not available", 503
    return f"""<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<script src='https://cdn.jsdelivr.net/npm/hls.js@latest'></script>
<style>body{{background:#000;color:#fff;text-align:center}}video{{width:95%;max-width:720px}}</style></head>
<body><h2 style="color:#00ffff">{channel.replace('_',' ').title()}</h2>
<video id='v' controls autoplay playsinline></video>
<script>if(Hls.isSupported()){{let h=new Hls();h.loadSource("{url}");h.attachMedia(document.getElementById('v'));}}
else{{document.getElementById('v').src="{url}";}}</script>
<div style="margin-top:10px"><a href='/' style="color:#00ffff">⬅ Home</a></div>
</body></html>"""

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
            try:
                proc.terminate()
            except Exception:
                pass
    return Response(generate(), mimetype="audio/mpeg")

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

    logging.info("🚀 Live TV + Playlist Radio server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)