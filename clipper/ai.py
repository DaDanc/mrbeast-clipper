"""AI bira momente za klipove (umjesto bodovanja po glasnoći i ključnim riječima).

AI dobije cijeli transkript s vremenima i brief kampanje, a vrati:
  - koje rečenice čine klip (početak i kraj na granici misli)
  - naslov na videu (kratak hook za prve sekunde)
  - opis objave (jedna rečenica u stilu "opisi" iz config.yaml)
  - ocjenu 1-10 i odbacuje klipove izvan konteksta, osjetljive ili prekinute

Radi s besplatnim Gemini ključem (secret GEMINI_API_KEY) ili s Claude ključem
(secret ANTHROPIC_API_KEY). Ako nema nijednog ključa, klipovi se biraju po starom.
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .transcribe import Segment


def provider() -> str | None:
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    return None


def available() -> bool:
    return provider() is not None


# ---------------------------------------------------------------- pozivi API-ja
def _ask_gemini(prompt: str, models: list[str]) -> str:
    """Probava modele redom. Ako je model zauzet (503/429), odmah ide na sljedeći;
    tek kad su svi zauzeti, malo pričeka i krene ispočetka (najviše 4 kruga)."""
    key = os.environ["GEMINI_API_KEY"].strip()
    last = None
    dead: set[str] = set()  # modeli koji ne postoje ili im je dnevna kvota potrošena
    for rnd in range(4):
        for model in models:
            if model in dead:
                continue
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
                    },
                    timeout=300,
                )
            except requests.RequestException as e:
                last = f"{model}: {e}"
                print(f"  ⚠️ {last}", flush=True)
                continue
            if r.status_code == 200:
                parts = r.json()["candidates"][0]["content"]["parts"]
                if rnd or last:
                    print(f"  ✅ odgovorio {model}", flush=True)
                return "".join(p.get("text", "") for p in parts)
            msg = r.text.lower()
            last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
            print(f"  ⚠️ {model}: HTTP {r.status_code}", flush=True)
            if r.status_code in (400, 401, 403) and ("api key" in msg or "permission" in msg):
                raise RuntimeError(f"Gemini ključ ne valja: {last}")
            if r.status_code not in (429, 500, 503) or "per day" in msg:
                dead.add(model)  # ne postoji / dnevna kvota – ne probavaj ga više
        if len(dead) == len(models):
            break
        wait = 15 * (rnd + 1)
        print(f"  … svi modeli zauzeti, čekam {wait} s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"Gemini nije odgovorio: {last}")


def _ask_anthropic(prompt: str, model: str) -> str:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": model, "max_tokens": 8000, "temperature": 0.4,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=300,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API: HTTP {r.status_code} {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def ask(prompt: str, cfg: dict) -> str:
    p = provider()
    if p == "gemini":
        models = cfg.get("ai_gemini_modeli") or ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
        return _ask_gemini(prompt, list(models))
    if p == "anthropic":
        return _ask_anthropic(prompt, cfg.get("ai_claude_model") or "claude-haiku-5-5")
    raise RuntimeError("Nema AI ključa (GEMINI_API_KEY ili ANTHROPIC_API_KEY).")


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


# ---------------------------------------------------------------- prompt
def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def build_prompt(segs: list[Segment], n: int, min_s: float, max_s: float, cfg: dict,
                 exclude: list[tuple[float, float]]) -> str:
    lines = [f"#{i} [{_fmt(s.start)}-{_fmt(s.end)}] {s.text}" for i, s in enumerate(segs)]
    examples = list((cfg.get("opisi") or {}).values())[:5]
    ex = "\n".join(f"- {e}" for e in examples) or "- Harry Connick Jr. refused to set foot inside Carnegie Hall for 45 years. The reason is his mom"
    excl = ", ".join(f"{_fmt(a)}-{_fmt(b)}" for a, b in exclude) or "nema"
    brief = str(cfg.get("brief") or "").strip() or "(nema posebnih pravila)"
    return f"""You are an expert short-form video editor. You cut long videos into viral TikTok/Shorts clips
that get paid views in a creator clipping campaign. Below is a timestamped transcript (one numbered segment per line).

CAMPAIGN BRIEF (must be followed, clips that break it don't get paid):
{brief}

Pick up to {n * 2} candidate clips, then grade each honestly. Rules for a good clip:
1. Length between {min_s:.0f} and {max_s:.0f} seconds (end time of last segment minus start time of first).
2. It must make sense to someone who never saw the video: starts at the beginning of a thought or question,
   NOT mid-sentence or mid-story; ends on a punchline, reveal or completed thought, NOT mid-sentence.
3. Strong first 3 seconds: a surprising statement, a question, a laugh, an emotional moment.
4. One story or idea per clip. Funny, surprising, emotional and "I didn't know that" moments do best.
5. Reject (score 1-3) anything out of context, confusing, where the transcript looks garbled/misheard,
   just ads/sponsor reads/intros/outros, or sensitive topics that could be misleading without context
   (someone's death, abuse, violence, health claims about a specific person).
6. Do NOT use these already used time ranges: {excl}.
7. Clips must not overlap each other.

For each clip write:
- "hook": on-screen title for the first 3 seconds, max 8 words, makes people want to keep watching,
  must be TRUE to what is said (no fake clickbait). Name the guest if known.
- "caption": one sentence for the post description, same style as these examples:
{ex}
  (name the guest, tell what is interesting without spoiling the end, max one emoji, no hashtags)
- "score": 1-10 how likely it is to get lots of views AND follow all rules (be strict, 8+ only for great ones)
- "why": max 12 words why

Answer ONLY with JSON in this exact shape:
{{"clips": [{{"from": <first segment number>, "to": <last segment number>, "hook": "...", "caption": "...", "score": 8, "why": "..."}}]}}

TRANSCRIPT:
""" + "\n".join(lines)


# ---------------------------------------------------------------- provjera odgovora
def _overlaps(a: float, b: float, ranges: list[tuple[float, float]], gap: float = 5) -> bool:
    return any(not (b + gap <= x or a >= y + gap) for x, y in ranges)


def validate(raw: dict, segs: list[Segment], n: int, min_s: float, max_s: float, min_score: float,
             exclude: list[tuple[float, float]]) -> list:
    from .highlights import Clip  # ovdje, da provjera postavki ne treba numpy

    items = raw.get("clips", []) if isinstance(raw, dict) else raw
    good: list[Clip] = []
    for it in sorted(items, key=lambda x: -float(x.get("score", 0) or 0)):
        try:
            i, j = int(it["from"]), int(it["to"])
            score = float(it.get("score", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if score < min_score or not (0 <= i <= j < len(segs)):
            continue
        # popravi dužinu na granicama rečenica ako je AI malo promašio
        while segs[j].end - segs[i].start < min_s and j + 1 < len(segs) \
                and segs[j + 1].end - segs[i].start <= max_s:
            j += 1
        while segs[j].end - segs[i].start > max_s and j > i:
            j -= 1
        start, end = segs[i].start, segs[j].end
        if not (min_s <= end - start <= max_s):
            print(f"  ✗ odbačen (dužina {end - start:.0f} s): {it.get('hook', '')}")
            continue
        if _overlaps(start, end, exclude + [(c.start, c.end) for c in good]):
            continue
        hook = re.sub(r"\s+", " ", str(it.get("hook", ""))).strip().strip('"')
        caption = re.sub(r"\s+", " ", str(it.get("caption", ""))).strip().strip('"')
        caption = re.sub(r"\s*#\w+", "", caption).strip()  # hashtagove dodajemo sami
        text = " ".join(s.text for s in segs[i : j + 1])
        good.append(Clip(start, end, score, hook or caption[:60], text, caption=caption or hook, ai=True))
        print(f"  ✓ {score:.0f}/10 [{_fmt(start)}-{_fmt(end)}] {hook}  ({it.get('why', '')})")
        if len(good) >= n:
            break
    good.sort(key=lambda c: c.start)
    return good


def pick_clips(segs: list[Segment], n: int, min_s: float, max_s: float, cfg: dict,
               exclude: list[tuple[float, float]] | None = None) -> list:
    exclude = exclude or []
    segs = [s for s in segs if s.text]
    print(f"▶ AI ({provider()}) bira momente iz {len(segs)} rečenica...", flush=True)
    raw = parse_json(ask(build_prompt(segs, n, min_s, max_s, cfg, exclude), cfg))
    clips = validate(raw, segs, n, min_s, max_s, float(cfg.get("ai_min_ocjena", 7)), exclude)
    print(f"  AI je odabrao {len(clips)} klipova.", flush=True)
    return clips
