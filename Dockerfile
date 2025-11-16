FROM node:18-slim

# Install Python + ffmpeg + system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Ensure Python is default
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install yt-dlp nightly + EJS solver
RUN pip install -U yt-dlp --pre
RUN pip install -U yt-dlp[ejs]

# Install global EJS runtime for challenge solving
RUN npm install -g ejs

# Environment variable for yt-dlp to use JS runtime
ENV YTDLP_USE_JS_RUNTIME=1

# Create cookies directory
RUN mkdir -p /mnt/data

# App directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

EXPOSE 8000

CMD ["python", "restream.py"]