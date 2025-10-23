# Use a lightweight Python base image
FROM python:3.11-slim

# Install system dependencies including ffmpeg (for audio processing) and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Install the latest yt-dlp binary globally
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app code
COPY . .

# Ensure persistent storage directory exists (if your app uses it for cookies, cache, etc.)
RUN mkdir -p /mnt/data

# Expose the port your Flask app runs on
EXPOSE 8000

# Use environment variable for FLASK_ENV to avoid dev warnings in production
ENV FLASK_ENV=production

# Start the Flask app
CMD ["python", "restream.py"]
