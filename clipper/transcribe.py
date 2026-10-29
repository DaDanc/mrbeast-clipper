"""Transkripcija govora s vremenom svake riječi (faster-whisper, radi na CPU-u)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def extract_audio(video: Path, wav: Path, stream: int | None = None) -> Path:
    """stream = koji audio trag koristiti (npr. 2 = centar/dijalog u 5.1 masteru TV serije)."""
    sel = ["-map", f"0:a:{int(stream)}"] if stream is not None else []
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *sel,
         "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )
    return wav


def transcribe(wav: Path, model_name: str = "small") -> list[Segment]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(wav), language="en", word_timestamps=True, vad_filter=True, beam_size=1
    )
    out: list[Segment] = []
    for s in segments:
        words = [Word(w.start, w.end, w.word.strip()) for w in (s.words or []) if w.word.strip()]
        out.append(Segment(s.start, s.end, s.text.strip(), words))
        print(f"  [{s.start:7.1f}s] {s.text.strip()[:80]}", flush=True)
    return out


def save(segments: list[Segment], path: Path) -> None:
    path.write_text(json.dumps([asdict(s) for s in segments], ensure_ascii=False))


def load(path: Path) -> list[Segment]:
    raw = json.loads(path.read_text())
    return [
        Segment(s["start"], s["end"], s["text"], [Word(**w) for w in s["words"]])
        for s in raw
    ]
