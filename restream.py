import os
import threading
import time
import subprocess
from flask import Flask, Response, request, render_template_string, redirect, url_for

# Config
COOKIES_PATH = os.environ.get('COOKIES_PATH', '/app/data/mnt/cookies.txt')
YTDLP_BIN = os.environ.get('YTDLP_BIN', 'yt-dlp')
FFMPEG_BIN = os.environ.get('FFMPEG_BIN', 'ffmpeg')
PORT = int(os.environ.get('PORT', 5000))
AUTO_PLAYLIST_URL = os.environ.get('AUTO_PLAYLIST_URL', None)  # new

app = Flask(__name__)

playlist_lock = threading.Lock()
playlist = []
current_index = 0

ADMIN_HTML = """
<!doctype html>
<title>YouTube Radio Admin</title>
<h1>YouTube Radio — Admin</h1>
{% if not auto_url %}
<form method="post" action="/admin/set_auto">
  <input name="url" placeholder="YouTube playlist URL" style="width:60%">
  <button type="submit">Set as auto-playlist (cycles automatically)</button>
</form>
{% else %}
<p>Auto-playlist URL: {{auto_url}}</p>
<form method="post" action="/admin/clear_auto">
  <button type="submit">Clear auto playlist</button>
</form>
{% endif %}
<form method="post" action="/admin/add" style="margin-top:20px">
  <input name="url" placeholder="YouTube video or playlist URL" style="width:60%">
  <button type="submit">Add to playlist manually</button>
</form>
<form method="post" action="/admin/clear" style="margin-top:10px">
  <button type="submit">Clear playlist</button>
</form>
<h2>Playlist</h2>
<ol>
{% for i,u in playlist %}
  <li>{{u}}</li>
{% endfor %}
</ol>
<p>Stream endpoint: <a href="/stream">/stream</a></p>
"""

def extract_playlist_items(playlist_url):
    """Use yt-dlp to list all video URLs from a playlist."""
    cmd = [YTDLP_BIN, '--cookies', COOKIES_PATH, '--flat-playlist',
           '--print', 'url', playlist_url]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=60)
        lines = out.strip().splitlines()
        # lines will be like “https://www.youtube.com/watch?v=VIDEOID”
        return [line.strip() for line in lines if line.strip()]
    except Exception as e:
        print("Error extracting playlist items:", e)
        return []

def ensure_auto_playlist_loaded():
    global playlist
    if AUTO_PLAYLIST_URL:
        with playlist_lock:
            if not playlist or playlist[0] != AUTO_PLAYLIST_URL:  # simple check
                items = extract_playlist_items(AUTO_PLAYLIST_URL)
                if items:
                    playlist = items.copy()

@app.before_first_request
def init_auto_playlist():
    if AUTO_PLAYLIST_URL:
        ensure_auto_playlist_loaded()

@app.route('/')
def index():
    return redirect(url_for('admin'))

@app.route('/admin')
def admin():
    with playlist_lock:
        items = list(enumerate(playlist))
    return render_template_string(ADMIN_HTML, playlist=items, auto_url=AUTO_PLAYLIST_URL)

@app.route('/admin/set_auto', methods=['POST'])
def admin_set_auto():
    url = request.form.get('url')
    if not url:
        return redirect(url_for('admin'))
    os.environ['AUTO_PLAYLIST_URL'] = url.strip()
    # Reload auto playlist now
    global AUTO_PLAYLIST_URL
    AUTO_PLAYLIST_URL = url.strip()
    ensure_auto_playlist_loaded()
    return redirect(url_for('admin'))

@app.route('/admin/clear_auto', methods=['POST'])
def admin_clear_auto():
    global AUTO_PLAYLIST_URL
    AUTO_PLAYLIST_URL = None
    with playlist_lock:
        playlist.clear()
    return redirect(url_for('admin'))

@app.route('/admin/add', methods=['POST'])
def admin_add():
    url = request.form.get('url')
    if not url:
        return redirect(url_for('admin'))
    with playlist_lock:
        playlist.append(url.strip())
    return redirect(url_for('admin'))

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    with playlist_lock:
        playlist.clear()
    return redirect(url_for('admin'))

@app.route('/stream')
def stream():
    global current_index
    def generator():
        while True:
            if AUTO_PLAYLIST_URL:
                ensure_auto_playlist_loaded()

            with playlist_lock:
                if not playlist:
                    time.sleep(1)
                    continue
                url = playlist[current_index % len(playlist)]
                current_index += 1

            audio_url = yt_audio_url(url)
            if not audio_url:
                audio_url = url

            proc = None
            try:
                proc = make_ffmpeg_proc(audio_url)
                if not proc or not proc.stdout:
                    time.sleep(1)
                    continue
                while True:
                    chunk = proc.stdout.read(16 * 1024)
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                print('stream error', e)
            finally:
                if proc:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    headers = {
        'Content-Type': 'audio/mpeg',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive'
    }
    return Response(generator(), headers=headers)

if __name__ == '__main__':
    if not os.path.exists(COOKIES_PATH):
        print(f'Warning: cookies file not found at {COOKIES_PATH}. Some videos may fail.\\n')
    app.run(host='0.0.0.0', port=PORT, threaded=True)