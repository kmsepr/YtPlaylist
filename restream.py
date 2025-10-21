import os
import threading
import time
import subprocess
from flask import Flask, Response, request, render_template_string, redirect, url_for

# ------------------------------
# Configuration
# ------------------------------
COOKIES_PATH = os.environ.get('COOKIES_PATH', '/app/data/mnt/cookies.txt')
YTDLP_BIN = os.environ.get('YTDLP_BIN', 'yt-dlp')
FFMPEG_BIN = os.environ.get('FFMPEG_BIN', 'ffmpeg')
PORT = int(os.environ.get('PORT', 8080))

app = Flask(__name__)

# ------------------------------
# Playlist (simple memory-based)
# ------------------------------
playlist_lock = threading.Lock()
playlist = [
    # Example: YouTube Lofi stream
    'https://www.youtube.com/watch?v=5qap5aO4i9A',
]
current_index = 0

# ------------------------------
# Admin Interface Template
# ------------------------------
ADMIN_HTML = """
<!doctype html>
<title>YouTube Radio Admin</title>
<h1>YouTube Radio — Admin</h1>
<form method="post" action="/admin/add">
  <input name="url" placeholder="YouTube video or playlist URL" style="width:60%">
  <button type="submit">Add to playlist</button>
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

# ------------------------------
# Helper Functions
# ------------------------------
def yt_audio_url(ytdlp_input_url):
    """Use yt-dlp to extract a direct audio URL."""
    cmd = [YTDLP_BIN, '--cookies', COOKIES_PATH, '-f', 'bestaudio', '--get-url', ytdlp_input_url]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, universal_newlines=True, timeout=30)
        url = out.strip().splitlines()[-1]
        return url
    except Exception:
        return None


def make_ffmpeg_proc(input_url):
    """Start ffmpeg to read `input_url` and output MP3 to stdout."""
    args = [
        FFMPEG_BIN,
        '-re',  # read input at native rate
        '-i', input_url,
        '-vn',  # disable video
        '-ac', '2',
        '-ar', '44100',
        '-f', 'mp3',
        '-'
    ]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

# ------------------------------
# Routes
# ------------------------------
@app.route('/')
def index():
    return redirect(url_for('admin'))


@app.route('/admin')
def admin():
    with playlist_lock:
        items = list(enumerate(playlist))
    return render_template_string(ADMIN_HTML, playlist=items)


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
    """Stream the playlist sequentially as continuous MP3 audio."""
    def generator():
        nonlocal current_index
        while True:
            with playlist_lock:
                if not playlist:
                    time.sleep(1)
                    continue
                url = playlist[current_index % len(playlist)]
                current_index = (current_index + 1) % len(playlist)

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


# ------------------------------
# Entry Point
# ------------------------------
if __name__ == '__main__':
    if not os.path.exists(COOKIES_PATH):
        print(f'Warning: cookies file not found at {COOKIES_PATH}. Some videos may fail.\n')
    app.run(host='0.0.0.0', port=PORT, threaded=True)