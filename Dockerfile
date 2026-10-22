FROM python:3.12-slim

# ffmpeg for audio extraction + caption burning, fonts-noto for Devanagari captions
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-noto-core fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py caption_engine.py hinglish.py .
COPY static ./static

# Whisper model size. Free servers (Render free = 512 MB RAM) need "base".
# On a bigger server set WHISPER_MODEL=small or medium for better Hindi accuracy.
ENV WHISPER_MODEL=base
EXPOSE 7860
# Render (and most hosts) assign their own PORT; fall back to 7860 (Hugging Face).
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
