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


def build_ass(clip: Clip, segments: list[Segment], path: Path, group: int = 3, show_hook: bool = True,
              layout: str = "blur", hook_text: str = "") -> Path:
    font = _font()
    full = layout == "full"
    cap_size = (104 if full else 92) if font == "Anton" else 86
    hook_size = (92 if full else 70) if font == "Anton" else 66
    # full: hook gore preko slike (ispod TikTokovih gumba), cijelo vrijeme; titlovi u donjoj trećini
    hook_margin = 250 if full else FG_Y - 260
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{cap_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1
Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,{hook_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # hook gore u prve 4 s (bijeli tekst na crnoj traci) – može se isključiti u configu
    text = (hook_text or clip.hook or "").strip()
    if show_hook and text:
        if full:  # od prvog kadra do kraja, bez fade-ina (prva sekunda je najvažnija)
            lines.append(f"Dialogue: 1,{_ts(0)},{_ts(clip.duration + 1)},Hook,,0,0,0,,{_esc(text.upper())}")
        else:
            lines.append(
                f"Dialogue: 1,{_ts(0)},{_ts(min(4.0, clip.duration))},Hook,,0,0,0,,"
                f"{{\\fad(150,250)}}{_esc(text.upper())}"
            )

    words = []
    for w in _words_in(segments, clip.start, clip.end):
        # Whisper ponekad razbije "$100,000" na "$100" + ",000" - spoji natrag
        if words and w.text[:1] in ",.%'" and len(w.text) > 1:
            p = words[-1]
            words[-1] = Word(p.start, w.end, p.text + w.text)
        else:
            words.append(w)
    cap_y = 1290 if full else FG_Y + FG_H + 170
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


def _size(video: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
                         capture_output=True, text=True).stdout.strip()
    try:
        w, h = (int(x) for x in out.splitlines()[0].split("x"))
        return w, h
    except Exception:
        return 1920, 1080


def face_center(video: Path, start: float, dur: float, samples: int = 9) -> float:
    """Vodoravni položaj lica (0-1) u klipu: medijan najvećeg lica u nekoliko kadrova."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return 0.5
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 ga nema → sredina
        return 0.5
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs = []
    for k in range(samples):
        t = start + dur * (k + 0.5) / samples
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                              "-frames:v", "1", "-vf", "scale=640:-2", "-f", "image2pipe",
                              "-vcodec", "png", "-"], capture_output=True).stdout
        if not raw:
            continue
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + w / 2) / img.shape[1])
    if not xs:
        return 0.5
    xs.sort()
    return float(xs[len(xs) // 2])


def shot_cuts(video: Path, start: float, dur: float, thr: float = 0.3) -> list[float]:
    """Vremena rezova kadra (u sekundama od početka klipa)."""
    import re as _re
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(video),
                        "-an", "-vf", f"scale=320:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    cuts = [float(x) for x in _re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    out = []
    for c in cuts:  # spoji rezove bliže od 1 s
        if c > 0.5 and (not out or c - out[-1] > 1.0):
            out.append(c)
    return out


def crop_x_expr(video: Path, clip: Clip, scaled_w: int) -> str:
    """Izraz za ffmpeg crop: za svaki kadar posebno centrira lice (tko je u kadru, taj je u sredini)."""
    def x_for(fx: float) -> int:
        return int(min(max(fx * scaled_w - W / 2, 0), max(scaled_w - W, 0)))

    cuts = shot_cuts(video, clip.start, clip.duration)[:40]
    bounds = [0.0] + cuts + [clip.duration]
    xs = []
    for a, b in zip(bounds, bounds[1:]):
        fx = face_center(video, clip.start + a, max(b - a, 0.3), samples=3 if b - a < 4 else 5)
        xs.append(x_for(fx))
    if len(xs) == 1:
        return str(xs[0])
    expr = str(xs[-1])
    for t, x in reversed(list(zip(cuts, xs[:-1]))):
        expr = f"if(lt(t\\,{t:.2f})\\,{x}\\,{expr})"
    return expr


def render(video: Path, clip: Clip, segments: list[Segment], out: Path, workdir: Path,
           show_hook: bool = True, audio_mix: list[int] | None = None,
           layout: str = "blur", hook_text: str = "") -> Path:
    """audio_mix = audio tragovi koji čine stereo miks (npr. [6, 7] u masteru TV serije).
    layout: "blur" = video u sredini, mutna pozadina; "full" = lice preko cijelog ekrana (9:16 izrez)."""
    ass = build_ass(clip, segments, workdir / (out.stem + ".ass"), show_hook=show_hook,
                    layout=layout, hook_text=hook_text)
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:")
    fonts_arg = str(FONTS_DIR).replace(":", "\\:")
    if layout == "full":
        sw, sh = _size(video)
        scaled_w = int(round(sw * H / sh / 2)) * 2
        x = crop_x_expr(video, clip, scaled_w)
        vf = (f"[0:v]scale={scaled_w}:{H},crop={W}:{H}:'{x}':0,fps=30,"
              f"ass='{ass_arg}':fontsdir='{fonts_arg}',format=yuv420p[v]")
    else:
      vf = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"scale={W // 8}:{H // 8},gblur=sigma=6,scale={W}:{H},eq=brightness=-0.12[bgb];"
        f"[fg]scale=-2:{FG_H},crop={W}:{FG_H}[fgc];"
        f"[bgb][fgc]overlay=0:{FG_Y},fps=30,"
        f"ass='{ass_arg}':fontsdir='{fonts_arg}',format=yuv420p[v]"
    )
    if audio_mix and len(audio_mix) > 1:
        ins = "".join(f"[0:a:{int(i)}]" for i in audio_mix)
        aud, amap = f";{ins}amerge=inputs={len(audio_mix)}[aout]", "[aout]"
    elif audio_mix:
        aud, amap = "", f"0:a:{int(audio_mix[0])}"
    else:
        aud, amap = "", "0:a:0?"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{clip.start:.2f}", "-t", f"{clip.duration:.2f}", "-i", str(video),
        "-filter_complex", vf + aud, "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out
