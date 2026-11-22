"""Vrhunac klipa (vrisak, dernjava, smijeh) po zvuku – da video ne počne dosadnim dijelom.

Ako je najglasniji trenutak kasno u klipu:
  1. teaser: prve ~2 s videa su sam vrhunac (gledatelj odmah vidi da se nešto događa),
  2. zatim klip od najviše `max_uvod_sekundi` prije vrhunca do kraja (dosadan početak se odreže).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 8000
WIN = 0.05      # s, jedan uzorak glasnoće
SMOOTH = 0.4    # s, izglađivanje – dulji zvuk (vrisak) pobjeđuje kratki pucanj iz igre


@dataclass
class Edit:
    peak: float           # s, vrhunac u originalu
    contrast: float       # dB iznad medijana klipa
    teaser: tuple[float, float] | None
    body_start: float     # s, odakle ide ostatak klipa
    reason: str


def loudness(video: Path) -> np.ndarray:
    """Glasnoća (dB) svakih WIN s, samo raspon ljudskog glasa (manje utjecaja eksplozija i muzike)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(RATE),
         "-af", "highpass=f=300,lowpass=f=3400", "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    n = int(RATE * WIN)
    if len(x) < n * 10:
        return np.zeros(0)
    x = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((x ** 2).mean(axis=1)) + 1e-6)


def plan(video: Path, duration: float, cfg: dict) -> Edit:
    teaser_len = float(cfg.get("teaser_sekundi", 2.0))
    max_intro = float(cfg.get("max_uvod_sekundi", 6.0))
    min_contrast = float(cfg.get("min_kontrast_db", 8.0))
    min_peak = float(cfg.get("vrhunac_nakon_sekundi", 3.5))

    db = loudness(video)
    if not len(db):
        return Edit(0, 0, None, 0, "nema zvuka")
    k = max(1, int(SMOOTH / WIN))
    sm = np.convolve(db, np.ones(k) / k, mode="same")
    edge = int(0.5 / WIN)
    i = int(np.argmax(sm[edge:-edge])) + edge if len(sm) > 2 * edge + 1 else int(np.argmax(sm))
    peak = i * WIN
    contrast = float(sm[i] - np.median(sm))

    if contrast < min_contrast:
        return Edit(peak, contrast, None, 0, f"nema izraženog vrhunca ({contrast:.0f} dB)")
    if peak < min_peak:
        return Edit(peak, contrast, None, 0, f"vrhunac već na početku ({peak:.1f} s)")
    # teaser: malo prije vrhunca (da se vidi što ga je izazvalo) do malo poslije
    t0 = max(0.0, peak - teaser_len * 0.35)
    t1 = min(duration, t0 + teaser_len)
    body = max(0.0, peak - max_intro)
    return Edit(peak, contrast, (t0, t1), body,
                f"vrhunac u {peak:.1f} s (+{contrast:.0f} dB) → teaser {t0:.1f}–{t1:.1f} s, klip od {body:.1f} s")


def apply(video: Path, e: Edit, out: Path) -> Path:
    """Spoji [teaser] + [klip od body_start]. Kratki fade na rezu da zvuk ne pukne."""
    if not e.teaser and e.body_start <= 0:
        return video
    parts, labels = [], []
    segs = ([e.teaser] if e.teaser else []) + [(e.body_start, None)]
    n = len(segs)
    parts.append(f"[0:v]split={n}" + "".join(f"[vi{j}]" for j in range(n)) +
                 f";[0:a]asplit={n}" + "".join(f"[ai{j}]" for j in range(n)))
    for j, (a, b) in enumerate(segs):
        rng = f"start={a:.3f}" + (f":end={b:.3f}" if b is not None else "")
        parts.append(f"[vi{j}]trim={rng},setpts=PTS-STARTPTS[v{j}]")
        fade_out = f",afade=t=out:st={b - a - 0.08:.3f}:d=0.08" if b is not None else ""
        parts.append(f"[ai{j}]atrim={rng},asetpts=PTS-STARTPTS,afade=t=in:d=0.05{fade_out}[a{j}]")
        labels.append(f"[v{j}][a{j}]")
    parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[v][a]")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", str(out)],
        check=True)
    return out
