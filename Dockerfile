FROM python:3.12-slim

# ffmpeg for audio extraction + caption burning, fonts-noto for Devanagari captions
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-noto-core fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py caption_engine.py hinglish.py transcribe_worker.py .
COPY static ./static

# Vosk Hindi model (small, ~40 MB download) baked into the image: it uses
# ~215 MB RAM vs Whisper-small's ~630 MB, so it fits free 512 MB servers
# and writes clean Devanagari (Whisper-base writes Hindi in Urdu script).
RUN python -c "import urllib.request, zipfile; urllib.request.urlretrieve('https://alphacephei.com/vosk/models/vosk-model-small-hi-0.22.zip', '/tmp/vosk.zip'); zipfile.ZipFile('/tmp/vosk.zip').extractall('/opt'); import os; os.rename('/opt/vosk-model-small-hi-0.22', '/opt/vosk-model-small-hi'); os.remove('/tmp/vosk.zip')"
ENV ENGINE=vosk
ENV VOSK_MODEL_PATH=/opt/vosk-model-small-hi
# English mode (translation) still uses Whisper via the worker subprocess.
ENV WHISPER_MODEL=base
EXPOSE 7860
# Render (and most hosts) assign their own PORT; fall back to 7860 (Hugging Face).
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
