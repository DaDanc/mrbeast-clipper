"""Dodaje "hook" naslov na vrh već gotovog klipa (iznad videa, preko zamućene pozadine).

Radi na gotovom klipu s Cloudinaryja, pa ne treba izvorna epizoda.
Tekst naslova piše Claude nakon provjere klipa (config "naslovi").
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import requests

# iste mjere kao u render.py (ne uvozimo render jer on traži numpy/whisper)
W, H = 1080, 1920
FG_H = 810
FG_Y = (H - FG_H) // 2
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"


def _font() -> str:
    return "Anton" if (FONTS_DIR / "Anton-Regular.ttf").exists() else "DejaVu Sans"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _ass(text: str, duration: float, path: Path) -> Path:
    font = _font()
    size = 100 if font == "Anton" else 80
    # tekst stoji tik iznad srednjeg videa (Alignment 2 = dolje-sredina, MarginV od dna ekrana)
    margin_v = H - (FG_Y - 45)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    t = _esc(text.upper())
    line = f"Dialogue: 2,{_ts(0)},{_ts(duration + 1)},Hook,,0,0,0,,{{\\fad(200,0)}}{t}"
    path.write_text(header + line + "\n", encoding="utf-8")
    return path


def _ts(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 60.0


def add_hook(video_url: str, text: str, workdir: Path, name: str) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    src = workdir / f"{name}-src.mp4"
    with requests.get(video_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(src, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    ass = _ass(text, _duration(src), workdir / f"{name}.ass")
    out = workdir / f"{name}.mp4"
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    fonts_arg = str(FONTS_DIR).replace(":", "\\:")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-vf", f"ass='{ass_arg}':fontsdir='{fonts_arg}',format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high",
        "-c:a", "copy", "-movflags", "+faststart", str(out),
    ], check=True)
    src.unlink(missing_ok=True)
    return out
