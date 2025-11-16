# COOKIES_PATH=/mnt/data/cookies.txt

FROM node:18-slim

# Install Python + system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-dev \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment
RUN python3 -m venv /opt/venv

# Activate venv
ENV PATH="/opt/venv/bin:$PATH"

# Install yt-dlp nightly + EJS solver inside venv
RUN pip install --upgrade pip
RUN pip install --pre yt-dlp
RUN pip install "yt-dlp[ejs]"
RUN npm install -g ejs

# Enable JS runtime
ENV YTDLP_USE_JS_RUNTIME=1

# Ensure cookies directory exists
RUN mkdir -p /mnt/data

WORKDIR /app

# Install Python app requirements inside the venv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application files
COPY . .

EXPOSE 8000

CMD ["python", "restream.py"]