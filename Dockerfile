# Use a lightweight Python base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libmagic-dev \
    curl \
    libmagic1 \
 && rm -rf /var/lib/apt/lists/*

# Install the latest yt-dlp binary
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app code
COPY . .

# Create a directory for persistent data (cookies/cache if needed)
RUN mkdir -p /mnt/data

# Expose the port that Gunicorn will run on
EXPOSE 8000

# Set environment to production
ENV FLASK_ENV=production

# Start the Flask app with Gunicorn
# -w 4: 4 workers, adjust based on your CPU
# -b 0.0.0.0:8000: bind to all interfaces
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "restream:app"]
