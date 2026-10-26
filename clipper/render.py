"""Renderira vertikalni 9:16 klip (1080x1920) s titlovima u viralnom stilu.

Izgled:
  - pozadina: isti video, zamućen i povećan preko cijelog ekrana
  - sredina: video izrezan na 4:3 da lica budu veća
  - gore: "hook" naslov u prve 4 sekunde
  - dolje-sredina: titlovi riječ po riječ, trenutna riječ žuta
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .highlights import Clip
from .transcribe import Segment, Word

W, H = 1080, 1920
FG_H = 810  # visina srednjeg videa (4:3 izrez)
FG_Y = (H - FG_H) // 2

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"


def _font() -> str:
    return "Anton" if (FONTS_DIR / "Anton-Regular.ttf").exists() else "DejaVu Sans"


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _words_in(segments: list[Segment], start: float, end: float) -> list[Word]:
    out = []
    for s in segments:
        if s.end < start or s.start > end:
            continue
        if s.words:
            out.extend(w for w in s.words if w.start >= start - 0.05 and w.end <= end + 0.3)
        else:  # nema vremena po riječi - ravnomjerno rasporedi
            toks = s.text.split()
            step = (s.end - s.start) / max(len(toks), 1)
            out.extend(Word(s.start + k * step, s.start + (k + 1) * step, t) for k, t in enumerate(toks))
    return out


def build_ass(clip: Clip, segments: list[Segment], path: Path, group: int = 3) -> Path:
    font = _font()
    cap_size = 92 if font == "Anton" else 78
    hook_size = 70 if font == "Anton" else 58
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{cap_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1
Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,{FG_Y - 260},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # hook gore u prve 4 s (bijeli tekst na crnoj traci)
    lines.append(
        f"Dialogue: 1,{_ts(0)},{_ts(min(4.0, clip.duration))},Hook,,0,0,0,,"
        f"{{\\fad(150,250)}}{_esc(clip.hook.upper())}"
    )

    words = []
    for w in _words_in(segments, clip.start, clip.end):
        # Whisper ponekad razbije "$100,000" na "$100" + ",000" - spoji natrag
        if words and w.text[:1] in ",.%'" and len(w.text) > 1:
            p = words[-1]
            words[-1] = Word(p.start, w.end, p.text + w.text)
        else:
            words.append(w)
    cap_y = FG_Y + FG_H + 170
    # grupe do `group` riječi, nova grupa uvijek nakon kraja rečenice
    chunks: list[tuple[int, list[Word]]] = []
    cur: list[Word] = []
    cur_start = 0
    for i, w in enumerate(words):
        if not cur:
            cur_start = i
        cur.append(w)
        if len(cur) >= group or w.text.rstrip().endswith((".", "!", "?")):
            chunks.append((cur_start, cur))
            cur = []
    if cur:
        chunks.append((cur_start, cur))

    for g, chunk in chunks:
        for k, w in enumerate(chunk):
            idx = g + k
            st = w.start - clip.start
            nxt = words[idx + 1].start if idx + 1 < len(words) else None
            en = w.end + 0.15
            if nxt is not None:
                en = nxt if nxt - w.end < 0.6 else min(en, nxt)
            en -= clip.start
            if en <= st:
                en = st + 0.12
            if nxt is not None and st >= nxt - clip.start:
                continue  # riječi s istim vremenom - preskoči da se ne preklapaju
            parts = []
            for m, x in enumerate(chunk):
                t = _esc(x.text.upper())
                parts.append(f"{{\\c&H00E6FF&}}{t}{{\\c&HFFFFFF&}}" if m == k else t)
            pop = "{\\fscx108\\fscy108\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
            lines.append(
                f"Dialogue: 0,{_ts(st)},{_ts(min(en, clip.duration))},Cap,,0,0,0,,"
                f"{{\\pos({W // 2},{cap_y})}}{pop}{' '.join(parts)}"
            )
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def render(video: Path, clip: Clip, segments: list[Segment], out: Path, workdir: Path) -> Path:
    ass = build_ass(clip, segments, workdir / (out.stem + ".ass"))
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    fonts_arg = str(FONTS_DIR).replace(":", "\\:")
    vf = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"scale={W // 8}:{H // 8},gblur=sigma=6,scale={W}:{H},eq=brightness=-0.12[bgb];"
        f"[fg]scale=-2:{FG_H},crop={W}:{FG_H}[fgc];"
        f"[bgb][fgc]overlay=0:{FG_Y},fps=30,"
        f"ass='{ass_arg}':fontsdir='{fonts_arg}',format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{clip.start:.2f}", "-t", f"{clip.duration:.2f}", "-i", str(video),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out
