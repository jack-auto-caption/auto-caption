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
import threading

_model = None
_model_lock = threading.Lock()
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


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        return _model


def transcribe(wav_path, language, task="transcribe"):
    """language: 'hi', 'en', ... or None for auto-detect.
    task='translate' makes Whisper output English whatever the spoken language."""
    model = get_model()
    segments, _info = model.transcribe(
        wav_path,
        language=language,
        task=task,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = (w.word or "").strip()
            if text:
                words.append({"word": text, "start": float(w.start), "end": float(w.end)})
    if not words:
        raise RuntimeError("No speech detected in this video.")
    return words


_PUNCT_END = (".", "।", "?", "!", ",", "…")


def group_lines(words, max_words=5, max_dur=2.8):
    """Group word timings into short caption lines."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        line_dur = w["end"] - cur[0]["start"]
        gap_next = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 99
        if (len(cur) >= max_words or line_dur >= max_dur
                or w["word"].endswith(_PUNCT_END) or gap_next > 0.7):
            lines.append(cur)
            cur = []
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
POSITIONS = {
    "bottom":       (2, 0.07),
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
    for line in lines:
        texts = [_esc(w["word"]) for w in line]
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
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{' '.join(parts)}"
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

    say("Listening and writing captions (Whisper)")
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
