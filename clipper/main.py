"""Glavni program. Pokreću ga GitHub Actions workflowi.

  python -m clipper.main make  --url LINK      -> napravi klipove i otvori Issue za svaki
  python -m clipper.main publish --issue BROJ  -> objavi klip iz Issuea preko Buffera
  python -m clipper.main links                 -> skupi linkove objava za Vyro
  python -m clipper.main check                 -> provjeri Buffer i Cloudinary postavke
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())

L_CLIP = "klip"
L_APPROVE = "objavi"
L_POSTED = "objavljeno"
L_LINKS = "linkovi"
TRACKER_TITLE = "📋 Linkovi za Vyro"


# ---------------------------------------------------------------- GitHub helperi
def gh(*args: str, capture: bool = True) -> str:
    res = subprocess.run(["gh", *args], capture_output=capture, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} nije uspio: {res.stderr.strip()}")
    return (res.stdout or "").strip()


def ensure_labels() -> None:
    for name, color, desc in [
        (L_CLIP, "1d76db", "Novi klip čeka pregled"),
        (L_APPROVE, "0e8a16", "Dodaj ovaj label da se klip objavi"),
        (L_POSTED, "5319e7", "Poslano u Buffer"),
        (L_LINKS, "fbca04", "Linkovi objava su skupljeni"),
    ]:
        subprocess.run(["gh", "label", "create", name, "--color", color, "--description", desc, "--force"],
                       capture_output=True)


def comment(issue: int, body: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
    gh("issue", "comment", str(issue), "--body-file", f.name)


def read_json_marker(text: str, marker: str) -> dict | None:
    m = re.search(rf"<!--{marker}\s*(\{{.*?\}})\s*-->", text, re.S)
    return json.loads(m.group(1)) if m else None


# ---------------------------------------------------------------- make
def fmt_time(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def cmd_make(url: str, max_videos: int) -> None:
    from . import fetch, highlights, hosting, render, transcribe

    ensure_labels()
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    print("▶ Preuzimam materijal...", flush=True)
    videos = fetch.fetch(url, work / "src", max_videos=max_videos)

    made = 0
    for vi, video in enumerate(videos):
        print(f"▶ Video {vi + 1}/{len(videos)}: {video.name}", flush=True)
        wav = transcribe.extract_audio(video, work / f"audio{vi}.wav")
        print("▶ Prepoznajem govor (ovo traje najduže)...", flush=True)
        segs = transcribe.transcribe(wav, CFG.get("whisper_model", "small"))
        if not segs:
            print("  Nema govora u videu, preskačem.")
            continue
        loud = highlights.loudness_per_second(wav)
        clips = highlights.find_clips(
            segs, loud, CFG["hype_words"], CFG["clips_per_video"], CFG["min_seconds"], CFG["max_seconds"]
        )
        stamp = time.strftime("%Y%m%d-%H%M")
        for ci, clip in enumerate(clips):
            name = f"{stamp}-v{vi}-c{ci}"
            out = work / f"{name}.mp4"
            print(f"▶ Renderiram klip {ci + 1}/{len(clips)} ({fmt_time(clip.start)}-{fmt_time(clip.end)})", flush=True)
            render.render(video, clip, segs, out, work)
            video_url = hosting.upload(out, name)
            thumb = re.sub(r"/upload/", "/upload/so_2,w_360/", video_url).rsplit(".", 1)[0] + ".jpg"

            caption = CFG["caption_template"].format(hook=clip.hook).strip()
            yt_title = CFG["youtube_title_template"].format(hook=clip.hook)[:100]
            data = {"video_url": video_url, "caption": caption, "yt_title": yt_title,
                    "source": video.name, "start": round(clip.start, 2), "end": round(clip.end, 2),
                    "score": round(clip.score, 2)}
            body = f"""[![pregled]({thumb})]({video_url})

**▶️ [Pogledaj klip]({video_url})** · {clip.duration:.0f} s · iz `{video.name}` ({fmt_time(clip.start)}–{fmt_time(clip.end)}) · ocjena {clip.score:.1f}

**Opis objave:**
```
{caption}
```

**Što sad?**
- Sviđa ti se → dodaj label **`{L_APPROVE}`** (desno: Labels). Klip ide na {", ".join(CFG["platforms"])}.
- Ne sviđa ti se → samo zatvori ovaj Issue.

<details><summary>Tekst klipa</summary>

{clip.text}
</details>

<!--CLIPDATA {json.dumps(data, ensure_ascii=False)} -->
"""
            title = f"🎬 {clip.hook[:70]}"
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(body)
            gh("issue", "create", "--title", title, "--body-file", f.name, "--label", L_CLIP)
            out.unlink(missing_ok=True)
            made += 1
    print(f"✅ Gotovo: {made} klipova čeka tvoj pregled u Issues.")


# ---------------------------------------------------------------- publish
def cmd_publish(issue: int) -> None:
    from . import buffer

    info = json.loads(gh("issue", "view", str(issue), "--json", "body,labels"))
    labels = {l["name"] for l in info["labels"]}
    if L_POSTED in labels:
        print("Već objavljeno, preskačem.")
        return
    data = read_json_marker(info["body"], "CLIPDATA")
    if not data:
        comment(issue, "⚠️ U ovom Issueu nema podataka o klipu, ne mogu objaviti.")
        return

    mode = CFG.get("post_mode", "shareNow")
    try:
        channels = buffer.get_channels(CFG["platforms"])
    except Exception as e:
        comment(issue, f"❌ Ne mogu se spojiti na Buffer: {e}")
        raise
    if not channels:
        comment(issue, f"❌ U Bufferu nema povezanih kanala za: {', '.join(CFG['platforms'])}.")
        sys.exit(1)

    done, lines = {}, []
    for ch in channels:
        try:
            post = buffer.create_video_post(ch, data["caption"], data["video_url"], data["yt_title"], mode)
            done[post["id"]] = ch["service"]
            lines.append(f"- ✅ **{ch['service']}** ({ch['name']}): poslano u Buffer")
        except Exception as e:
            lines.append(f"- ❌ **{ch['service']}** ({ch['name']}): {e}")
    marker = json.dumps({"posts": done})
    comment(issue, "### Objava\n" + "\n".join(lines)
            + "\n\nLinkove objava skupit ću sam unutar sat vremena i staviti ih u Issue **"
            + TRACKER_TITLE + f"**.\n\n<!--BUFFER_POSTS {marker} -->")
    if done:
        gh("issue", "edit", str(issue), "--add-label", L_POSTED)
    else:
        sys.exit(1)


# ---------------------------------------------------------------- links
def tracker_issue() -> int:
    found = json.loads(gh("issue", "list", "--state", "open", "--search", f'in:title "{TRACKER_TITLE}"',
                          "--json", "number,title"))
    for i in found:
        if i["title"] == TRACKER_TITLE:
            return i["number"]
    body = ("Ovdje se skupljaju linkovi svih objavljenih klipova.\n\n"
            "Svaki link predaj na **vyro.com** → tvoja MrBeast kampanja → **Submit Post**.\n"
            "Predaj ih što prije: pregledi se broje tek od predaje, a budžet kampanje se brzo potroši.\n")
    url = gh("issue", "create", "--title", TRACKER_TITLE, "--body", body)
    num = int(url.rstrip("/").split("/")[-1])
    subprocess.run(["gh", "issue", "pin", str(num)], capture_output=True)
    return num


def cmd_links() -> None:
    from . import buffer

    ensure_labels()
    issues = json.loads(gh("issue", "list", "--state", "all", "--label", L_POSTED, "--limit", "100",
                           "--json", "number,title,labels"))
    pending = [i for i in issues if L_LINKS not in {l["name"] for l in i["labels"]}]
    if not pending:
        print("Nema novih objava.")
        return
    tracker = None
    for iss in pending:
        n = iss["number"]
        comments = json.loads(gh("issue", "view", str(n), "--json", "comments"))["comments"]
        posts = {}
        for c in comments:
            m = read_json_marker(c["body"], "BUFFER_POSTS")
            if m:
                posts.update(m["posts"])
        results, finished = [], True
        for pid, service in posts.items():
            try:
                p = buffer.get_post(pid)
            except Exception as e:
                results.append(f"- {service}: ne mogu provjeriti ({e})")
                continue
            if p.get("externalLink"):
                results.append(f"- **{service}**: {p['externalLink']}")
            elif str(p["status"]).lower() == "error" or p.get("error"):
                msg = (p.get("error") or {}).get("message", "nepoznata greška")
                results.append(f"- ❌ **{service}**: objava nije uspjela – {msg}")
            elif str(p["status"]).lower() == "sent":
                results.append(f"- **{service}**: objavljeno, ali Buffer nije vratio link – "
                               "kopiraj ga iz aplikacije")
            else:
                finished = False
        if not finished:
            print(f"#{n}: još se objavljuje, provjerit ću kasnije.")
            continue
        text = "\n".join(results) or "- (nema objava)"
        comment(n, "### 🔗 Linkovi za Vyro\n" + text)
        tracker = tracker or tracker_issue()
        comment(tracker, f"**{iss['title']}** (#{n})\n{text}")
        gh("issue", "edit", str(n), "--add-label", L_LINKS)
        gh("issue", "close", str(n))
        print(f"#{n}: linkovi skupljeni.")


# ---------------------------------------------------------------- check
def cmd_check() -> None:
    from . import buffer

    ok = True
    print("▶ Buffer...")
    try:
        chans = buffer.get_channels(["tiktok", "instagram", "youtube", "facebook", "twitter"])
        if not chans:
            print("  ⚠️ Spojen, ali nema povezanih TikTok/Instagram/YouTube kanala.")
            ok = False
        for c in chans:
            mark = "✅" if c["service"].lower() in [p.lower() for p in CFG["platforms"]] else "  (ne koristi se)"
            print(f"  {mark} {c['service']}: {c['name']}")
        for s in CFG["platforms"]:
            if s.lower() not in {c["service"].lower() for c in chans}:
                print(f"  ⚠️ {s} nije povezan u Bufferu – na njega se neće objavljivati.")
            else:
                print(f"     {s} postavke objave: {buffer.build_metadata(s, 'Test naslov')}")
    except Exception as e:
        print(f"  ❌ {e}")
        ok = False
    print("▶ Cloudinary...")
    if os.environ.get("CLOUDINARY_URL", "").startswith("cloudinary://"):
        try:
            import cloudinary, cloudinary.api
            cloudinary.config(secure=True)
            cloudinary.api.ping()
            print("  ✅ radi")
        except Exception as e:
            print(f"  ❌ {e}")
            ok = False
    else:
        print("  ❌ secret CLOUDINARY_URL nedostaje ili ne počinje s cloudinary://")
        ok = False
    print("\n✅ SVE SPREMNO" if ok else "\n❌ Nešto ne valja – pogledaj gore.")
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--url", required=True)
    m.add_argument("--max-videos", type=int, default=1)
    pb = sub.add_parser("publish")
    pb.add_argument("--issue", type=int, required=True)
    sub.add_parser("links")
    sub.add_parser("check")
    a = p.parse_args()
    if a.cmd == "make":
        cmd_make(a.url, a.max_videos)
    elif a.cmd == "publish":
        cmd_publish(a.issue)
    elif a.cmd == "links":
        cmd_links()
    else:
        cmd_check()


if __name__ == "__main__":
    main()
