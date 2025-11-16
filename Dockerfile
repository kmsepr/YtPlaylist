# Use a lightweight Python base image
FROM python:3.11-slim

# Install system dependencies including ffmpeg + Node.js for yt-dlp JS challenges
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
    nodejs \
    npm \
 && rm -rf /var/lib/apt/lists/*

# Install yt-dlp nightly (required to solve n-challenge)
RUN pip install -U yt-dlp --pre
RUN pip install -U yt-dlp[ejs]

# OPTIONAL: install standalone yt-dlp binary for fallback
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
    -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Install global EJS (yt-dlp uses it for signature-challenge solving)
RUN npm install -g ejs

# Enable JS runtime for yt-dlp
ENV YTDLP_USE_JS_RUNTIME=1

# Ensure cookies directory exists
RUN mkdir -p /mnt/data

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app code
COPY . .

# Expose port for the Flask app
EXPOSE 8000

# Start the Flask app
CMD ["python", "restream.py"]