import os
import subprocess
import tempfile
from flask import Flask, request, send_file, render_template_string, abort

app = Flask(__name__)

HTML_FORM = """
<!DOCTYPE html>
<html>
<head>
  <title>MP3 Converter (to 16kbps)</title>
  <style>
    body { font-family: sans-serif; background: #111; color: #eee; text-align: center; padding: 40px; }
    input[type=text] { width: 90%; padding: 10px; font-size: 16px; border-radius: 6px; border: none; }
    button { margin-top: 20px; padding: 10px 20px; font-size: 16px; border: none; border-radius: 6px;
             background: #28a745; color: white; cursor: pointer; }
    button:hover { background: #218838; }
  </style>
</head>
<body>
  <h2>🎵 MP3 Converter (64kbps ➜ 16kbps)</h2>
  <form method="get" action="/convert">
    <input type="text" name="url" placeholder="Paste direct MP3 URL here..." required>
    <br><button type="submit">Convert</button>
  </form>
  <p style="margin-top:30px;color:#aaa;">Example: https://s60tube.io.vn/relay?u=https%3A%2F%2Fvideo.2yxa.mobi%2Fusers%2F2yxa_ru_1b883oYcAmo_imp812548_432055.mp3</p>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_FORM)

@app.route('/convert')
def convert():
    mp3_url = request.args.get('url')
    if not mp3_url:
        return abort(400, "Missing ?url parameter")

    # Create temporary files
    tmp_input = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_output = tempfile.NamedTemporaryFile(suffix="_16kbps.mp3", delete=False)
    tmp_input.close()
    tmp_output.close()

    try:
        # Use ffmpeg to re-encode to 16 kbps
        cmd = [
            "ffmpeg", "-y",
            "-i", mp3_url,
            "-b:a", "16k",
            "-ar", "22050",
            "-ac", "1",
            tmp_output.name
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # Serve converted file for download
        return send_file(tmp_output.name, as_attachment=True, download_name="converted_16kbps.mp3")

    except subprocess.CalledProcessError as e:
        return f"<pre>❌ FFmpeg error:\n{e.stderr.decode(errors='ignore')}</pre>", 500
    finally:
        # Cleanup temp input file if it exists
        if os.path.exists(tmp_input.name):
            os.remove(tmp_input.name)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)