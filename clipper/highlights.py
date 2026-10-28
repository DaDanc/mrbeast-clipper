"""Bira najjače momente iz videa.

Bodovanje svakog kandidata (komad od 25-55 s koji počinje i završava na granici rečenice):
  - glasnoća zvuka (vrištanje, reakcije, publika) u odnosu na prosjek videa
  - "hype" riječi iz config.yaml (million, win, eliminated...)
  - gustoća govora (puno riječi = puno se događa)
  - jak početak: prvih 3 s mora biti glasno/zanimljivo, inače ljudi skrolaju dalje
"""
from __future__ import annotations

import re
import wave
from dataclasses import dataclass

import numpy as np

from .transcribe import Segment


@dataclass
class Clip:
    start: float
    end: float
    score: float
    hook: str
    text: str
    caption: str = ""   # opis objave koji je napisao AI (prazno = koristi hook)
    ai: bool = False    # True = AI je odabrao i provjerio ovaj klip

    @property
    def duration(self) -> float:
        return self.end - self.start


def loudness_per_second(wav_path) -> np.ndarray:
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    n = len(data) // sr
    if n == 0:
        return np.zeros(1)
    frames = data[: n * sr].reshape(n, sr)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-9)
    db = 20 * np.log10(rms + 1e-9)
    std = db.std() or 1.0
    return (db - db.mean()) / std  # z-score: 0 = prosjek videa


def _hype_hits(text: str, hype_words: list[str]) -> int:
    t = text.lower()
    hits = 0
    for w in hype_words:
        w = w.lower()
        if w.isalpha():
            hits += len(re.findall(rf"\b{re.escape(w)}\b", t))
        else:
            hits += t.count(w)
    hits += len(re.findall(r"\$?\d[\d,]*(?:\.\d+)?\s*(?:k|million|thousand|dollars)?", t))
    hits += t.count("!")
    return hits


def _clean_hook(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip("-–—").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "..."


def find_clips(
    segments: list[Segment],
    loud: np.ndarray,
    hype_words: list[str],
    n_clips: int,
    min_s: float,
    max_s: float,
    exclude: list[tuple[float, float]] | None = None,
) -> list[Clip]:
    """exclude = vremenski rasponi već iskorištenih klipova (ne ponavljaj iste momente)."""
    exclude = exclude or []
    segs = [s for s in segments if s.text]
    total = segs[-1].end if segs else 0
    cands: list[Clip] = []

    def loud_mean(a: float, b: float) -> float:
        i, j = int(a), max(int(a) + 1, int(b))
        return float(loud[i:j].mean()) if i < len(loud) else -1.0

    for i, first in enumerate(segs):
        if first.start < 3:  # preskoči intro
            continue
        text_parts = []
        for j in range(i, len(segs)):
            last = segs[j]
            dur = last.end - first.start
            text_parts.append(last.text)
            if dur > max_s:
                break
            if dur < min_s:
                continue
            text = " ".join(text_parts)
            words = sum(len(s.words) or len(s.text.split()) for s in segs[i : j + 1])
            density = words / dur
            hype = _hype_hits(text, hype_words)
            body_loud = loud_mean(first.start, last.end)
            peak = float(np.percentile(loud[int(first.start) : int(last.end) + 1], 90)) if int(first.start) < len(loud) else 0
            hook_loud = loud_mean(first.start, first.start + 3)
            hook_hype = _hype_hits(first.text, hype_words)
            ends_clean = last.text.rstrip().endswith((".", "!", "?"))

            score = (
                1.2 * body_loud
                + 0.8 * peak
                + 0.6 * min(hype, 8)
                + 0.5 * min(density, 4)
                + 0.8 * hook_loud
                + 0.7 * min(hook_hype, 3)
                + (0.5 if ends_clean else -0.5)
            )
            hook_src = max(
                segs[i : min(j + 1, i + 3)],
                key=lambda s: _hype_hits(s.text, hype_words) + 0.01 * len(s.text),
            ).text
            cands.append(Clip(first.start, last.end, score, _clean_hook(hook_src), text))

    cands.sort(key=lambda c: c.score, reverse=True)
    chosen: list[Clip] = []
    used = [Clip(a, b, 0, "", "") for a, b in exclude]
    for c in cands:
        if all(c.end + 5 <= o.start or c.start >= o.end + 5 for o in chosen + used):
            chosen.append(c)
        if len(chosen) >= n_clips:
            break
    chosen.sort(key=lambda c: c.start)
    print(f"  {len(cands)} kandidata, odabrano {len(chosen)} (video traje {total/60:.1f} min)")
    return chosen
