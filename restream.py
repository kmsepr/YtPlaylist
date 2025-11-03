import os
import subprocess
import tempfile
from flask import Flask, request, send_file, render_template_string, abort

app = Flask(__name__)

# Path to your cookies file
COOKIES_FILE = "/mnt/data/cookies.txt"

HTML_FORM = """
<!DOCTYPE html>
<html>
<head>
  <title>YouTube ➜ MP3 (16kbps)</title>
  <style>
    body { font-family: sans-serif; background: #111; color: #eee; text-align: center; padding: 40px; }
    input[type=text] { width: 90%; padding: 10px; font-size: 16px; border-radius: 6px; border: none; }
    button { margin-top: 20px; padding: 10px 20px; font-size: 16px; border: none; border-radius: 6px;
             background: #28a745; color: white; cursor: pointer; }
    button:hover { background: #218838; }
  </style>
</head>
<body>
  <h2>🎧 YouTube ➜ MP3 Converter (16kbps)</h2>
  <form method="get" action="/convert">
    <input type="text" name="url" placeholder="Paste YouTube URL here..." required>
    <br><button type="submit">Convert</button>
  </form>
  <p style="margin-top:30px;color:#aaa;">Example: https://www.youtube.com/watch?v=dQw4w9WgXcQ</p>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_FORM)

@app.route("/convert")
def convert():
    yt_url = request.args.get("url")
    if not yt_url:
        return abort(400, "Missing ?url parameter")

    tmpdir = tempfile.mkdtemp()
    tmp_audio = os.path.join(tmpdir, "audio.mp3")
    output_16k = os.path.join(tmpdir, "converted_16kbps.mp3")

    try:
        # ---------------------------
        # Step 1: Download with yt-dlp
        # ---------------------------
        cmd_download = [
            "yt-dlp",
            "-f", "bestaudio",
            "--extract-audio", "--audio-format", "mp3",
            "--audio-quality", "64K",
            "--cookies", COOKIES_FILE,
            "-o", tmp_audio,
            yt_url
        ]

        subprocess.run(cmd_download, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # ---------------------------
        # Step 2: Convert to 16 kbps
        # ---------------------------
        cmd_convert = [
            "ffmpeg", "-y",
            "-i", tmp_audio,
            "-b:a", "16k",
            "-ar", "22050",
            "-ac", "1",
            output_16k
        ]
        subprocess.run(cmd_convert, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        return send_file(output_16k, as_attachment=True, download_name="youtube_16kbps.mp3")

    except subprocess.CalledProcessError as e:
        return f"<pre>❌ Error:\n{e.stderr.decode(errors='ignore')}</pre>", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)