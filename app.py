"""
Auto Caption Website - backend.

Upload a video -> get back the SAME video with captions burned in.
No SRT files for the user; captions are part of the video itself.

Run:  uvicorn app:app --host 0.0.0.0 --port 7860
"""

import os
import shutil
import threading
import uuid

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import caption_engine

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(BASE, "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MAX_BYTES = 500 * 1024 * 1024  # 500 MB

app = FastAPI(title="Auto Caption")
jobs = {}
jobs_lock = threading.Lock()


def set_job(job_id, **kw):
    with jobs_lock:
        jobs[job_id].update(kw)


def run_job(job_id, input_path, workdir, mode, position):
    try:
        result = caption_engine.caption_video(
            input_path, workdir, mode=mode, position=position,
            progress=lambda s: set_job(job_id, stage=s),
        )
        set_job(job_id, status="done", stage="Done",
                lines=result["lines"], transcript=result["transcript"][:500])
    except Exception as e:  # surface the real reason to the page
        set_job(job_id, status="error", stage="Failed", error=str(e)[:600])


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...),
                     mode: str = Form("hindi"),
                     position: str = Form("bottom")):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Only video files: {', '.join(sorted(ALLOWED))}")
    if mode not in caption_engine.MODES:
        mode = "hindi"
    if position not in caption_engine.POSITIONS:
        position = "bottom"

    # One job at a time: the free server has only 512 MB RAM. Two jobs
    # running together (e.g. a retry while the first is still working)
    # blow past it and the whole instance restarts, killing BOTH jobs
    # (verified live 2026-10-22: three OOM restarts in one afternoon).
    with jobs_lock:
        busy = any(j["status"] == "working" for j in jobs.values())
    if busy:
        raise HTTPException(409, "Ek video abhi ban raha hai — use pura hone do, "
                                   "phir dusra daalna. Free server ek time pe ek "
                                   "hi video utha pata hai.")

    job_id = uuid.uuid4().hex[:12]
    workdir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(workdir)
    input_path = os.path.join(workdir, "input" + ext)

    size = 0
    with open(input_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                shutil.rmtree(workdir, ignore_errors=True)
                raise HTTPException(400, "File too big (max 500 MB)")
            f.write(chunk)

    with jobs_lock:
        jobs[job_id] = {"status": "working", "stage": "Starting", "error": None}
    threading.Thread(target=run_job,
                     args=(job_id, input_path, workdir, mode, position),
                     daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str):
    path = os.path.join(JOBS_DIR, job_id, "captioned.mp4")
    if not os.path.exists(path):
        raise HTTPException(404, "Video not ready")
    return FileResponse(path, media_type="video/mp4", filename="captioned-video.mp4")


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(BASE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
