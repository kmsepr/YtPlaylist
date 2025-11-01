import os
import time
import random
import json
import threading
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from flask import Flask, Response, render_template_string, abort, stream_with_context, request, send_file
import pandas as pd
import re
import io

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

# ==============================================================
# 🎶 YouTube Playlist Radio SECTION
# ==============================================================

LOG_PATH = "/mnt/data/radio.log"
COOKIES_PATH = "/mnt/data/cookies.txt"
CACHE_FILE = "/mnt/data/playlist_cache.json"
os.makedirs(DOWNLOAD_DIR := "/mnt/data/radio_cache", exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=3)
logging.getLogger().addHandler(handler)

PLAYLISTS = {
    "kas_ranker": "https://youtube.com/playlist?list=PLS2N6hORhZbuZsS_2u5H_z6oOKDQT1NRZ",
    "ca": "https://youtube.com/playlist?list=PLYKzjRvMAyci_W5xYyIXHBoR63eefUadL",
    "samastha": "https://youtube.com/playlist?list=PLgkREi1Wpr-XgNxocxs3iPj61pqMhi9bv",
    "youtube_playlist": "https://youtube.com/playlist?list=PLlXSv-ic4-yJj2djMawc8XqqtCn1BVAc2",
}

STREAMS_RADIO = {}
MAX_QUEUE = 128
REFRESH_INTERVAL = 1800  # 30 min

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
                f'-o - --quiet --no-warnings "{url}" | '
                f'ffmpeg -loglevel quiet -i pipe:0 -ac 1 -ar 44100 -b:a 64k -f mp3 pipe:1'
            )
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                while len(s["QUEUE"]) >= MAX_QUEUE:
                    time.sleep(0.05)
                s["QUEUE"].append(chunk)

            proc.wait()
            logging.info(f"[{name}] ✅ Track completed.")
            time.sleep(2)

        except Exception as e:
            logging.error(f"[{name}] Worker error: {e}")
            time.sleep(5)

@app.route("/radio")
def radio_home():
    playlists = list(PLAYLISTS.keys())
    html = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎧 YouTube Radio</title>
<style>
body{background:#000;color:#0f0;font-family:Arial,sans-serif;text-align:center;margin:0;padding:12px}
a{display:block;color:#0f0;text-decoration:none;border:1px solid #0f0;padding:10px;margin:8px;border-radius:8px;font-size:18px}
a:hover{background:#0f0;color:#000}
</style></head><body>
<h2>🎶 YouTube Playlist Radio</h2>
{% for p in playlists %}
  <a href="/radio/listen/{{p}}">▶ {{p|capitalize}}</a>
{% endfor %}
</body></html>"""
    return render_template_string(html, playlists=playlists)

@app.route("/radio/listen/<name>")
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
    return Response(stream_with_context(gen()), mimetype="audio/mpeg")

# ==============================================================
# 📘 MCQ Converter SECTION
# ==============================================================

@app.route("/mcq", methods=["GET"])
def mcq_index():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>MCQ Converter</title></head>
    <body>
    <h2>📘 MCQ to Excel Converter</h2>
    <form method="post" action="/mcq/convert">
      <textarea name="mcq_text" rows="20" cols="80" placeholder="Paste your MCQs here..."></textarea><br>
      <input type="submit" value="Convert to Excel">
    </form>
    </body></html>
    """

def parse_mcqs(text):
    text = text.replace('\r\n', '\n').replace('\r','\n')
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    rows = []
    qno, qtext_lines, opts, answer, explanation_lines = None, [], {}, None, []
    capturing_expl = False
    for line in lines:
        m_opt = re.match(r'^[\(\[]?([a-dA-D])[\)\:\-]*\s*(.*)', line)
        if m_opt and not capturing_expl:
            opt_text = re.sub(r'^[\.\)\:\-\s]+', '', m_opt.group(2).strip())
            opts[m_opt.group(1).lower()] = opt_text
            continue
        m_ans = re.match(r'^(\d+)\.\s*([A-Da-d])$', line)
        if m_ans:
            answer = m_ans.group(2).upper()
            qno = m_ans.group(1)
            capturing_expl = True
            explanation_lines = []
            continue
        if capturing_expl:
            if re.match(r'^\d+\.', line):
                if opts and answer:
                    question_full = '\n'.join(qtext_lines).strip() + '\n' + \
                        f"A) {opts.get('a','')}\nB) {opts.get('b','')}\nC) {opts.get('c','')}\nD) {opts.get('d','')}"
                    rows.append([qno, question_full, 'A','B','C','D',
                                 {"A":1,"B":2,"C":3,"D":4}[answer],
                                 ' '.join(explanation_lines).strip()])
                qno, qtext_lines, opts, answer = None, [], {}, None
                capturing_expl = False
                m_q = re.match(r'^(\d+)\.(.*)', line)
                if m_q:
                    qno = m_q.group(1)
                    qtext_lines = [m_q.group(2).strip()]
                continue
            else:
                explanation_lines.append(line)
                continue
        m_q = re.match(r'^(\d+)\.(.*)', line)
        if m_q:
            qno = m_q.group(1)
            qtext_lines = [m_q.group(2).strip()]
            continue
        if qno:
            qtext_lines.append(line)
    if opts and answer:
        question_full = '\n'.join(qtext_lines).strip() + '\n' + \
            f"A) {opts.get('a','')}\nB) {opts.get('b','')}\nC) {opts.get('c','')}\nD) {opts.get('d','')}"
        rows.append([qno, question_full, 'A','B','C','D',
                     {"A":1,"B":2,"C":3,"D":4}[answer],
                     ' '.join(explanation_lines).strip()])
    return rows

@app.route('/mcq/convert', methods=['POST'])
def convert():
    text = request.form.get("mcq_text", "").strip()
    if not text:
        return "No text provided!", 400
    rows = parse_mcqs(text)
    if not rows:
        return "Could not parse any MCQs. Please check format.", 400
    df = pd.DataFrame(rows, columns=["Sl.No","Question","A","B","C","D","Correct Answer","Explanation"])
    output = io.BytesIO()
    df.to_excel(output, index=False, header=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="mcqs.xlsx")

# ==============================================================
# 🚀 START SERVER
# ==============================================================

if __name__ == "__main__":
    for pname in PLAYLISTS:
        STREAMS_RADIO[pname] = {
            "IDS": load_playlist_ids_radio(pname),
            "INDEX": 0,
            "QUEUE": deque(),
            "LAST_REFRESH": time.time(),
        }
        threading.Thread(target=stream_worker_radio, args=(pname,), daemon=True).start()

    logging.info("🚀 Combined Server running at http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)