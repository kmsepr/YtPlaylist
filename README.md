# 🎧 Multi-Playlist YouTube Radio (MP3 Streaming)

A lightweight Python Flask application that streams audio from YouTube playlists as MP3, designed for **Internet radio use**. Supports multiple playlists with unique streaming URLs, caching, and automatic playlist refresh. Built with `yt-dlp` and `ffmpeg` for stable streaming.

---

## Features

- Stream **multiple YouTube playlists** simultaneously.
- **Download / force download MP3** via `/stream/<playlist>` endpoint.
- **Mobile-friendly web interface** to listen to playlists via `/listen/<playlist>`.
- **Automatic playlist refresh** every 30 minutes.
- **Caching of video IDs** to avoid repeated playlist scraping.
- **Direct audio streaming using `yt-dlp -g`** to reduce 403 Forbidden errors.
- Compatible with **small devices and Internet radio hardware**.
- Logs activity to `/mnt/data/radio.log`.

---

## Requirements

- Python 3.11+
- [Flask](https://flask.palletsprojects.com/)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [ffmpeg](https://ffmpeg.org/)
- Cookies file from YouTube (`cookies.txt`) for logged-in sessions (optional, recommended for age-restricted content)

---

## Installation

1. Clone this repository:

```bash
git clone https://github.com/yourusername/youtube-radio.git
cd youtube-radio