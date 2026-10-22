"""
Caption engine: video -> burned-in karaoke captions.

Pipeline (all local, no paid API):
  1. ffprobe the video (width / height / duration)
  2. ffmpeg extracts 16kHz mono audio
  3. faster-whisper transcribes with word-level timestamps
     (language is FORCED when the user picks one - this is what stops
      Hindi speech being mis-detected as Urdu, the CapCut problem)
  4. Words are grouped into short caption lines and written as an
     .ass file where the currently-spoken word is highlighted yellow
     and the rest of the line is white (karaoke style)
  5. ffmpeg burns the .ass into the video and returns a finished .mp4
"""

import json
import os
import subprocess

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")


def _run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:3])}...\n{p.stderr[-800:]}")
    return p


def probe(video_path):
    p = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
        "-of", "json", video_path,
    ])
    info = json.loads(p.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(info["format"]["duration"])


def extract_audio(video_path, wav_path):
    _run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
          "-vn", "-ac", "1", "-ar", "16000", wav_path])


def transcribe(wav_path, language, task="transcribe"):
    """language: 'hi', 'en', ... or None for auto-detect.
    task='translate' makes Whisper output English whatever the spoken language.

    Runs in a subprocess (transcribe_worker.py) so the Whisper model's
    memory is fully freed when it exits - on a 512 MB free server the
    web process + model in one process OOMs mid-job (verified live)."""
    import subprocess
    import sys
    out_json = wav_path + ".words.json"
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcribe_worker.py")
    env = dict(os.environ, WHISPER_MODEL=MODEL_SIZE, OMP_NUM_THREADS="2")
    p = subprocess.run(
        [sys.executable, worker, wav_path, language or "none", task, out_json],
        capture_output=True, text=True, env=env,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Transcription failed:\n{p.stderr[-600:]}")
    with open(out_json, encoding="utf-8") as f:
        words = json.load(f)
    if not words:
        raise RuntimeError("No speech detected in this video.")
    return words


_PUNCT_END = (".", "।", "?", "!", ",", "…")


def group_lines(words, max_words=5, max_dur=2.8, max_chars=24):
    """Group word timings into short caption lines.

    max_chars matters: a line that is too wide wraps onto a second line
    in the renderer, and a bottom-anchored two-line block sits higher
    than a one-line block - the captions visibly jump up and down.
    Lines are kept short enough to always stay on ONE line."""
    lines, cur = [], []
    cur_chars = 0
    for i, w in enumerate(words):
        wlen = len(w["word"]) + (1 if cur else 0)
        if cur and cur_chars + wlen > max_chars:
            lines.append(cur)
            cur, cur_chars = [], 0
            wlen = len(w["word"])
        cur.append(w)
        cur_chars += wlen
        line_dur = w["end"] - cur[0]["start"]
        gap_next = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 99
        if (len(cur) >= max_words or line_dur >= max_dur
                or w["word"].endswith(_PUNCT_END) or gap_next > 0.7):
            lines.append(cur)
            cur, cur_chars = [], 0
    if cur:
        lines.append(cur)
    return lines


def _ass_time(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


# Caption positions: name -> (ASS alignment, vertical margin as fraction of height)
# ASS alignment grid: 7 8 9 top / 4 5 6 middle / 1 2 3 bottom (left center right)
# "bar" is top-anchored (alignment 8, margin from the TOP): it places the
# caption right under the picture, inside the bottom black bar of the
# Socho-Zara layout (720x1280: picture ends at ~78% of the height, the
# caption starts at ~79%) - measured from Jack's reference video.
POSITIONS = {
    "bottom":       (2, 0.07),
    "bar":          (8, 0.78),
    "mid":          (2, 0.30),
    "center":       (5, 0.0),
    "top":          (8, 0.07),
    "bottom-left":  (1, 0.07),
    "bottom-right": (3, 0.07),
    "top-left":     (7, 0.07),
    "top-right":    (9, 0.07),
}


def build_ass(lines, width, height, position, ass_path):
    """One ASS event per spoken word: that word yellow, the rest white."""
    fontsize = max(28, round(height * 0.034))
    outline = max(2, round(fontsize * 0.07))
    alignment, mv_frac = POSITIONS.get(position, POSITIONS["bottom"])
    margin_v = round(height * mv_frac)
    side = max(16, round(width * 0.04))
    margin_l = side if alignment in (1, 4, 7) else 20
    margin_r = side if alignment in (3, 6, 9) else 20

    header = f"""[Script Info]
Title: Auto Captions
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Noto Sans Devanagari,{fontsize},&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},1,{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    avail_w = width - margin_l - margin_r
    for line in lines:
        texts = [_esc(w["word"]) for w in line]
        # Safety net: if a line still estimates too wide for one line,
        # shrink its font for these events so it can never wrap (a wrapped
        # line is what makes captions jump up and down).
        est_w = len(" ".join(texts)) * fontsize * 0.58
        fs_tag = ""
        if est_w > avail_w:
            fs_line = max(20, int(fontsize * avail_w / est_w))
            fs_tag = f"{{\\fs{fs_line}}}"
        for i, w in enumerate(line):
            start = w["start"]
            end = line[i + 1]["start"] if i + 1 < len(line) else w["end"]
            end = max(end, start + 0.12)
            parts = []
            for j, t in enumerate(texts):
                if j == i:
                    parts.append("{\\1c&H0000FFFF&}" + t + "{\\1c&H00FFFFFF&}")
                else:
                    parts.append(t)
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{fs_tag}{' '.join(parts)}"
            )
        # hold the full line (all white) through any trailing pause up to next line start
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")
    return len(events)


def burn(video_path, ass_name, width, height, out_path, workdir):
    vf = f"subtitles={ass_name}:original_size={width}x{height}"
    _run(["ffmpeg", "-y", "-v", "error", "-i", os.path.abspath(video_path),
          "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", os.path.abspath(out_path)],
         cwd=workdir)


MODES = ("hindi", "hinglish", "english", "original")


def caption_video(input_path, workdir, mode="hindi", position="bottom",
                  style=None, progress=None):
    """Full pipeline. progress(stage: str) is called as stages advance.

    mode:
      hindi    - spoken Hindi -> Devanagari captions (language forced to Hindi)
      hinglish - spoken Hindi -> Roman Hindi captions (sarkari naukri ki lain)
      english  - any spoken language -> English captions (Whisper translation)
      original - captions in whatever language is spoken, as spoken
    """
    def say(s):
        if progress:
            progress(s)

    if style is not None:  # legacy name for position
        position = style
    if position not in POSITIONS:
        position = "bottom"

    os.makedirs(workdir, exist_ok=True)
    say("Reading video")
    width, height, _dur = probe(input_path)

    wav = os.path.join(workdir, "audio.wav")
    say("Extracting audio")
    extract_audio(input_path, wav)

    say("Listening and writing captions")
    if mode == "english":
        words = transcribe(wav, None, task="translate")
    elif mode in ("hindi", "hinglish"):
        words = transcribe(wav, "hi")
    else:  # original
        words = transcribe(wav, None)

    if mode == "hinglish":
        from hinglish import to_hinglish
        for w in words:
            w["word"] = to_hinglish(w["word"])

    lines = group_lines(words)
    say(f"Styling {len(lines)} caption lines")
    build_ass(lines, width, height, position, os.path.join(workdir, "captions.ass"))

    out = os.path.join(workdir, "captioned.mp4")
    say("Burning captions into video")
    burn(input_path, "captions.ass", width, height, out, workdir)

    say("Done")
    return {"output": out, "lines": len(lines), "words": len(words),
            "transcript": " ".join(w["word"] for w in words)}
