"""Montaža vertikalnog klipa 1080x1920 (ffmpeg).

  Varijanta A (zadana): mutna povećana pozadina + originalni 16:9 klip po sredini.
  Varijanta B (streamer ima "facecam" u config.json): gore facecam, dolje igra.
  Titlovi riječ po riječ (trenutna riječ žuta) u donjoj trećini, hook naslov na vrhu prve ~3 s.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .transcribe import Segment, Word

W, H = 1080, 1920
FG_H = 608                      # A: 16:9 klip preko cijele širine
FG_Y = (H - FG_H) // 2          # 656
CAM_H = 760                     # B: visina facecama gore
GAME_H = H - CAM_H              # B: visina igre dolje (1160)

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"

EMOTES = {"lul", "lol", "kekw", "omegalul", "pog", "pogchamp", "poggers", "kappa", "monkas", "sadge",
          "pepega", "pepelaugh", "lulw", "icant", "aware", "clueless", "copium", "xd", "nah", "lmao", "lmfao"}


# ---------------------------------------------------------------- hook iz naslova
def clean_title(title: str, max_words: int = 6) -> str:
    """Naslov Twitch klipa bez emojija, @, #, linkova, emoteova i ponavljanja. Prazno = neupotrebljiv."""
    t = re.sub(r"https?://\S+|@\w+|#\w+", " ", title or "")
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)                 # "(nsfw)", "[clip]"
    t = t.encode("ascii", "ignore").decode()                # emojiji i ostali ne-ASCII znakovi
    t = re.sub(r"([!?.,])\1+", r"\1", t)                    # "???" → "?", "...." → "."
    t = re.sub(r"(\w)\1{2,}", r"\1\1", t)                   # "NAHHHH" → "NAHH"
    words = [w for w in t.replace("|", " ").split()
             if re.sub(r"\W", "", w).lower() not in EMOTES and re.search(r"[A-Za-z0-9]", w)]
    words = words[:max_words]
    out = " ".join(words).strip(" ,.-:;")
    return out if len(re.sub(r"[^A-Za-z]", "", out)) >= 4 else ""


# ---------------------------------------------------------------- titlovi (ASS)
def _font() -> str:
    return "Anton" if (FONTS_DIR / "Anton-Regular.ttf").exists() else "DejaVu Sans"


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _words(segments: list[Segment]) -> list[Word]:
    out: list[Word] = []
    for s in segments:
        ws = s.words or []
        if not ws:  # nema vremena po riječi – ravnomjerno rasporedi
            toks = s.text.split()
            step = (s.end - s.start) / max(len(toks), 1)
            ws = [Word(s.start + k * step, s.start + (k + 1) * step, t) for k, t in enumerate(toks)]
        for w in ws:
            # Whisper zna razbiti "$100,000" na "$100" + ",000" – spoji natrag
            if out and w.text[:1] in ",.%'" and len(w.text) > 1:
                p = out[-1]
                out[-1] = Word(p.start, w.end, p.text + w.text)
            else:
                out.append(w)
    return out


def build_ass(segments: list[Segment], duration: float, hook: str, hook_secs: float,
              layout: str, path: Path, group: int = 3) -> Path:
    font = _font()
    big = font == "Anton"
    cap_size, hook_size = (100, 84) if big else (80, 64)
    cap_y = 1420 if layout == "A" else 1480                 # donja trećina
    hook_y = FG_Y - 150 if layout == "A" else CAM_H          # A: iznad klipa, B: na spoju facecam/igra
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{cap_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,8,3,5,70,70,0,1
Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,1,0,3,16,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(min(hook_secs, duration))},Hook,,0,0,0,,"
                     f"{{\\pos({W // 2},{hook_y})\\fad(0,200)}}{_esc(hook.upper())}")

    words = _words(segments)
    chunks: list[tuple[int, list[Word]]] = []          # do `group` riječi, nova grupa nakon kraja rečenice
    cur: list[Word] = []
    first = 0
    for i, w in enumerate(words):
        if not cur:
            first = i
        cur.append(w)
        if len(cur) >= group or w.text.rstrip().endswith((".", "!", "?")):
            chunks.append((first, cur))
            cur = []
    if cur:
        chunks.append((first, cur))

    for g, chunk in chunks:
        for k, w in enumerate(chunk):
            idx = g + k
            st = w.start
            nxt = words[idx + 1].start if idx + 1 < len(words) else None
            en = w.end + 0.2
            if nxt is not None:
                en = nxt if nxt - w.end < 0.6 else min(en, nxt)
            if nxt is not None and st >= nxt:
                continue  # dvije riječi s istim vremenom – preskoči da se ne preklapaju
            if en <= st:
                en = st + 0.12
            parts = []
            for m, x in enumerate(chunk):
                t = _esc(x.text.upper())
                parts.append(f"{{\\c&H00E6FF&\\fscx108\\fscy108}}{t}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
                             if m == k else t)
            lines.append(f"Dialogue: 1,{_ts(st)},{_ts(min(en, duration))},Cap,,0,0,0,,"
                         f"{{\\pos({W // 2},{cap_y})}}" + " ".join(parts))
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- ffmpeg
def probe_duration(video: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(video)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def _filter(layout: str, cam: dict | None) -> str:
    if layout == "B" and cam:
        x, y, w, h = (float(cam[k]) for k in ("x", "y", "w", "h"))
        return (
            "[0:v]split=2[a][b];"
            f"[a]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={W}:{CAM_H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{CAM_H},setsar=1[cam];"
            f"[b]crop=ih*{W}/{GAME_H}:ih:(iw-ow)/2:0,scale={W}:{GAME_H},setsar=1[game];"
            "[cam][game]vstack=inputs=2[v0]"
        )
    return (
        "[0:v]split=2[a][b];"
        "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
        f"scale={W}:{H},eq=brightness=-0.06,setsar=1[bg];"
        f"[b]scale={W}:-2,setsar=1[fg];"
        "[bg][fg]overlay=0:(H-h)/2[v0]"
    )


def render(video: Path, ass: Path, out: Path, layout: str, cam: dict | None) -> Path:
    fonts = FONTS_DIR if FONTS_DIR.exists() else ROOT
    graph = _filter(layout, cam) + f";[v0]subtitles={ass.name}:fontsdir={fonts}[v]"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video.resolve()),
         "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
         "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out.resolve())],
        check=True, cwd=ass.parent,
    )
    return out
