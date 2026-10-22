# Auto Caption Website

Upload a video → download the same video with captions **burned in**.
No SRT files. The caption is part of the video itself.

- Word-by-word **karaoke captions**: white text, the word being spoken turns **yellow**
- **4 caption languages** (pick on the page):
  - **Hindi** — Devanagari captions. Hindi is **forced** (`language=hi`), so Hindi speech is never mis-detected as Urdu
  - **Hinglish** — Roman Hindi captions (*desh seva ki lain nahin hai*)
  - **English** — captions translated to English, whatever the spoken language
  - **Original** — captions in the spoken language, as spoken
- **8 caption positions** (pick on the page): Bottom Center, Mid-Down, Center,
  Top Center, Bottom Left, Bottom Right, Top Left, Top Right
- 100% free to run — uses the open-source Whisper AI model on your own server, no per-minute API fees

## How it works

1. You upload a video on the web page
2. FFmpeg pulls the audio out
3. Whisper (faster-whisper) listens and writes every word with its exact timing
4. Words are grouped into short lines and styled as karaoke captions
5. FFmpeg burns the captions into the video → you download the finished MP4

A 45–55 sec short takes about 1–2 minutes on a free CPU server.

## Run it on your own computer

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 7860
```

Open http://localhost:7860

You also need `ffmpeg` installed and a font with Devanagari support
(e.g. fonts-noto) for Hindi captions.

## Put it online FREE (Render) — the free route

> Note: Hugging Face Spaces used to be the free route, but HF now charges
> $9/month (PRO) just to create Docker Spaces. Render's free web service
> still runs this Docker app for ₹0.

1. Make a free account at **github.com** (email verification only, no card)
2. Create a new **public** repository named `auto-caption` and upload
   everything from this folder (`app.py`, `caption_engine.py`, `hinglish.py`,
   `requirements.txt`, `Dockerfile`, `render.yaml`, and the `static` folder)
3. Make a free account at **render.com** → "Get started" → sign up **with GitHub**
4. Dashboard → **New + → Web Service** → connect the `auto-caption` repo
5. Render reads `render.yaml`: Docker runtime, **Free** plan → **Create Web Service**
6. Wait for the build (5–10 min first time). Your site goes live at
   `https://auto-caption-xxxx.onrender.com`

Free-plan reality: the server sleeps after ~15 min idle (first open then
takes 1–2 min to wake), and with 512 MB RAM it uses the lighter `base`
Whisper model — captions take a few minutes for a 45-sec video. It works,
it's free, it's just patient.

## Make captions more accurate / faster

In the Space settings → Variables, or in the Dockerfile:

- `WHISPER_MODEL=medium` → better Hindi accuracy, slower
- `WHISPER_MODEL=base` → faster, a bit less accurate
- Default is `small` (good balance)

## Files

| File | What it is |
|---|---|
| `app.py` | Website backend (upload, job status, download) |
| `caption_engine.py` | The caption pipeline (Whisper → karaoke ASS → burn) |
| `hinglish.py` | Devanagari → Hinglish (Roman) transliteration with spoken-Hindi schwa rules |
| `static/index.html` | The upload page |
| `Dockerfile` | For Render / any Docker host (listens on `$PORT`, defaults 7860) |
| `render.yaml` | Render free web-service config (Docker, free plan, base model) |
| `requirements.txt` | Python packages (note: `av==14.2.0` is pinned on purpose — newer PyAV breaks faster-whisper) |
