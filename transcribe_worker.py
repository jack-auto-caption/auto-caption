"""
Transcription worker - runs as a SEPARATE process.

Why: on a 512 MB free server, the web server and the speech model
cannot live in the same process (together they exceed the RAM limit
and the whole instance gets killed mid-job). This worker loads the
model, transcribes, writes the word timings to a JSON file and exits,
freeing ALL its memory before the caption-burning step starts.

Engines:
  ENGINE=vosk (default on the free server) - Vosk Hindi model.
      ~215 MB peak, clean Devanagari, word timings. Used for hindi /
      hinglish / original modes (audio is treated as Hindi).
  ENGINE=whisper - faster-whisper (WHISPER_MODEL env, default small).
      Used for english mode (task=translate), which Vosk cannot do.

Usage: python transcribe_worker.py <audio.wav> <language|none> <task> <out.json>
"""

import json
import os
import sys


def run_vosk(wav, out_path):
    import wave
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    model_path = os.environ.get("VOSK_MODEL_PATH", "/opt/vosk-model-small-hi")
    rec = KaldiRecognizer(Model(model_path), 16000)
    rec.SetWords(True)
    words = []
    with wave.open(wav) as wf:
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                for w in json.loads(rec.Result()).get("result", []):
                    words.append({"word": w["word"],
                                  "start": float(w["start"]),
                                  "end": float(w["end"])})
    for w in json.loads(rec.FinalResult()).get("result", []):
        words.append({"word": w["word"],
                      "start": float(w["start"]),
                      "end": float(w["end"])})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)


def run_whisper(wav, language, task, out_path):
    from faster_whisper import WhisperModel

    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"),
                         device="cpu", compute_type="int8", cpu_threads=2)
    segments, _info = model.transcribe(
        wav,
        language=None if language == "none" else language,
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
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)


def main():
    wav, language, task, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    engine = os.environ.get("ENGINE", "whisper")
    if engine == "vosk" and task != "translate":
        run_vosk(wav, out_path)
    else:
        run_whisper(wav, language, task, out_path)


if __name__ == "__main__":
    main()
