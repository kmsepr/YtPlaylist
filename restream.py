import subprocess
import json
import logging
from flask import Flask, Response, stream_with_context

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
COOKIES_PATH = "/mnt/data/cookies.txt"

CHANNELS = {
    "max": "https://youtube.com/@maxvelocitywx/videos",
    "furqan": "https://youtube.com/@alfurqan4991/videos",
    "rahmani": "https://www.youtube.com/@ShajahanRahmaniOfficial/videos",
    "vallathorukatha": "https://www.youtube.com/@babu_ramachandran/videos",
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

def fetch_latest_video_url(name, channel_url):
    try:
        result = subprocess.run([
            "yt-dlp",
            "--dump-single-json",
            "--playlist-end", "1",
            "--cookies", COOKIES_PATH,
            "--user-agent", FIXED_USER_AGENT,
            channel_url
        ], capture_output=True, text=True, check=True)

        data = json.loads(result.stdout)
        video_id = data['entries'][0]['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        logging.info(f"✅ [{name}] Video URL fetched successfully")
        return video_url

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ [{name}] yt-dlp failed: {e}")
        logging.error(f"[{name}] yt-dlp stderr:\n{e.stderr.strip()}")
        return None
    except Exception as e:
        logging.error(f"❌ [{name}] General error: {e}")
        return None

@app.route("/<channel>.mp3")
def stream_channel(channel):
    if channel not in CHANNELS:
        return "Invalid channel", 404

    video_url = fetch_latest_video_url(channel, CHANNELS[channel])
    if not video_url:
        return "Could not fetch video", 500

    def generate():
        yt = subprocess.Popen([
            "yt-dlp",
            "-f", "bestaudio",
            "--cookies", COOKIES_PATH,
            "--user-agent", FIXED_USER_AGENT,
            "-o", "-", video_url
        ], stdout=subprocess.PIPE)

        ff = subprocess.Popen([
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "mp3",
            "-ab", "64k",
            "-ar", "22050",
            "-ac", "1",
            "-hide_banner",
            "-loglevel", "quiet",
            "pipe:1"
        ], stdin=yt.stdout, stdout=subprocess.PIPE)

        yt.stdout.close()
        while True:
            chunk = ff.stdout.read(4096)
            if not chunk:
                break
            yield chunk

    return Response(stream_with_context(generate()), mimetype="audio/mpeg")

@app.route("/")
def index():
    links = "".join(f'<li><a href="/{name}.mp3">{name}</a></li>' for name in CHANNELS)
    return f"<h3>YouTube Live Audio</h3><ul>{links}</ul>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)