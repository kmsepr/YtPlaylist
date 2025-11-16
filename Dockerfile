# COOKIES_PATH=/mnt/data/cookies.txt

# Base image
FROM python:3.11-slim

# Install system dependencies + Node.js (for yt-dlp EJS solver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
    nodejs \
    npm \
 && rm -rf /var/lib/apt/lists/*

# Create Python virtual environment (PEP 668 requirement)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip inside venv
RUN pip install --upgrade pip setuptools wheel

# Install yt-dlp nightly + EJS support
RUN pip install --pre yt-dlp
RUN pip install "yt-dlp[ejs]"

# Install ejs runtime globally
RUN npm install -g ejs

# Force yt-dlp to use Node for the JS challenge solver
ENV YTDLP_USE_JS_RUNTIME=1
ENV YTDLP_JS_ENGINE="node"
ENV YTDLP_JS_RUNTIME="/usr/bin/node"

# Working directory
WORKDIR /app

# Install Python dependencies for Flask app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Ensure cookies directory exists
RUN mkdir -p /mnt/data

# Expose Flask port
EXPOSE 8000

# Run Flask app
CMD ["python", "restream.py"]