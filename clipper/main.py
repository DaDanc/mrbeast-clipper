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


def used_ranges() -> dict[str, list[tuple[float, float]]]:
    """Već napravljeni klipovi po izvornom videu, da se isti momenti ne ponavljaju."""
    out: dict[str, list[tuple[float, float]]] = {}
    try:
        issues = json.loads(gh("issue", "list", "--state", "all", "--label", L_CLIP, "--limit", "500",
                               "--json", "body"))
    except Exception:
        return out
    for i in issues:
        d = read_json_marker(i.get("body") or "", "CLIPDATA")
        if d and "start" in d and "end" in d:
            out.setdefault(d.get("source", ""), []).append((float(d["start"]), float(d["end"])))
    return out


def cmd_make(url: str, max_videos: int, hashtags: str = "", n_clips: int = 0) -> None:
    from . import fetch, highlights, hosting, render, transcribe

    n_clips = n_clips or int(CFG["clips_per_video"])
    tags = (hashtags or CFG.get("hashtags", "")).strip()
    print(f"▶ Hashtagovi za objave: {tags or '(nema)'}", flush=True)
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
        used = used_ranges().get(video.name, [])
        if used:
            print(f"  Preskačem {len(used)} već iskorištenih momenata iz ovog videa.", flush=True)
        clips = highlights.find_clips(
            segs, loud, CFG["hype_words"], n_clips, CFG["min_seconds"], CFG["max_seconds"], exclude=used
        )
        stamp = time.strftime("%Y%m%d-%H%M")
        created: list[tuple[float, int]] = []
        for ci, clip in enumerate(clips):
            name = f"{stamp}-v{vi}-c{ci}"
            out = work / f"{name}.mp4"
            print(f"▶ Renderiram klip {ci + 1}/{len(clips)} ({fmt_time(clip.start)}-{fmt_time(clip.end)})", flush=True)
            render.render(video, clip, segs, out, work)
            video_url = hosting.upload(out, name)
            thumb = re.sub(r"/upload/", "/upload/so_2,w_360/", video_url).rsplit(".", 1)[0] + ".jpg"

            caption = CFG["caption_template"].format(hook=clip.hook, hashtags=tags).strip()
            yt_title = CFG["youtube_title_template"].format(hook=clip.hook, hashtags=tags)[:100]
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
            url_issue = gh("issue", "create", "--title", title, "--body-file", f.name, "--label", L_CLIP)
            created.append((clip.score, int(url_issue.rstrip("/").split("/")[-1])))
            out.unlink(missing_ok=True)
            made += 1

        n_auto = int(CFG.get("auto_publish", 0) or 0)
        if n_auto > 0 and created:
            best = sorted(created, reverse=True)[:n_auto]
            print(f"▶ Automatski objavljujem {len(best)} najbolja klipa: {[n for _, n in best]}", flush=True)
            for _, num in best:
                try:
                    gh("issue", "edit", str(num), "--add-label", L_APPROVE)
                    cmd_publish(num)
                except (Exception, SystemExit) as e:
                    print(f"  ⚠️ Issue #{num} nije objavljen: {e}")
    print(f"✅ Gotovo: napravljeno {made} klipova.")


# ---------------------------------------------------------------- termini
def _parse_iso(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def next_slot(taken: list) -> "datetime":
    """Prvi slobodan termin iz config post_times (najmanje 15 min od sada,
    najmanje 30 min razmaka od već zakazanih objava na tom kanalu)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(CFG.get("timezone", "Europe/Zagreb"))
    now = datetime.now(tz) + timedelta(minutes=15)
    times = sorted(CFG.get("post_times") or ["18:00", "20:30", "23:00"])
    for day in range(0, 60):
        d = (now + timedelta(days=day)).date()
        for t in times:
            hh, mm = (int(x) for x in t.split(":"))
            slot = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            if slot < now:
                continue
            if all(abs((slot - x).total_seconds()) >= 30 * 60 for x in taken):
                return slot
    raise RuntimeError("Nema slobodnog termina u sljedećih 60 dana.")


def _utc_iso(dt) -> str:
    from datetime import timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _local(dt) -> str:
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(CFG.get("timezone", "Europe/Zagreb"))).strftime("%d.%m. u %H:%M")


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
            due = None
            when = "poslano u Buffer"
            if mode == "schedule":
                taken = [_parse_iso(p["dueAt"]) for p in buffer.scheduled_posts(ch["id"])]
                slot = next_slot(taken)
                due = _utc_iso(slot)
                when = f"zakazano za {_local(slot)}"
            post = buffer.create_video_post(ch, data["caption"], data["video_url"], data["yt_title"],
                                            mode, due_at=due)
            done[post["id"]] = ch["service"]
            lines.append(f"- ✅ **{ch['service']}** ({ch['name']}): {when}")
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


# ---------------------------------------------------------------- daily
def owner_mention() -> str:
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    return f"@{owner} " if owner else ""


def cmd_daily() -> None:
    """Svaki dan: dopuni Buffer red do `daily_posts` objava najboljim neobjavljenim klipovima."""
    from datetime import date
    from . import buffer

    end = str(CFG.get("campaign_end") or "").strip()
    if end and date.today().isoformat() > end:
        print(f"Kampanja je završila ({end}), ne objavljujem ništa.")
        return

    want = int(CFG.get("daily_posts", 3) or 0)
    channels = buffer.get_channels(CFG["platforms"])
    if not channels or want <= 0:
        print("Nema kanala ili je daily_posts = 0.")
        return
    waiting = max(len(buffer.scheduled_posts(ch["id"])) for ch in channels)
    need = max(0, want - waiting)
    print(f"▶ U Bufferu već čeka {waiting} objava po kanalu, cilj je {want} → objavljujem {need}.")
    if need == 0:
        return

    issues = json.loads(gh("issue", "list", "--state", "open", "--label", L_CLIP, "--limit", "200",
                           "--json", "number,title,body,labels"))
    tags = str(CFG.get("hashtags", "") or "").strip()
    cands = []
    for i in issues:
        names = {l["name"] for l in i["labels"]}
        if L_POSTED in names:
            continue
        d = read_json_marker(i.get("body") or "", "CLIPDATA")
        # samo klipovi trenutne kampanje (opis mora sadržavati njezine hashtagove)
        if d and tags and tags not in d.get("caption", ""):
            continue
        if d:
            cands.append((float(d.get("score", 0)), i["number"], i["title"]))
    cands.sort(reverse=True)

    if not cands:
        tracker = tracker_issue()
        comment(tracker, f"{owner_mention()}⚠️ **Ponestalo je klipova.** Sutra nema objava dok ne pokreneš "
                         "**1. Napravi klipove** s materijalom nove (ili iste) kampanje.")
        print("Nema neobjavljenih klipova – poslana obavijest.")
        return

    for score, num, title in cands[:need]:
        print(f"  → #{num} (ocjena {score:.1f}) {title}")
        try:
            gh("issue", "edit", str(num), "--add-label", L_APPROVE)
            cmd_publish(num)
        except (Exception, SystemExit) as e:
            print(f"  ⚠️ #{num} nije objavljen: {e}")

    left = len(cands) - min(need, len(cands))
    if left < want:
        tracker = tracker_issue()
        comment(tracker, f"{owner_mention()}ℹ️ Ostalo je još samo **{left}** neobjavljenih klipova. "
                         "Uskoro pokreni **1. Napravi klipove** da objave ne stanu.")


# ---------------------------------------------------------------- reschedule
def cmd_reschedule() -> None:
    """Sve objave koje čekaju u Bufferu presloži na termine iz config post_times."""
    from . import buffer

    for ch in buffer.get_channels(CFG["platforms"]):
        posts = buffer.scheduled_posts(ch["id"])
        print(f"▶ {ch['service']} ({ch['name']}): {len(posts)} objava čeka")
        taken: list = []
        for p in posts:
            slot = next_slot(taken)
            taken.append(slot)
            old = _local(_parse_iso(p["dueAt"]))
            try:
                buffer.set_post_time(p, ch["service"], _utc_iso(slot))
                print(f"   {old} → {_local(slot)}   {p['text'][:50]!r}")
            except Exception as e:
                print(f"   ⚠️ {p['text'][:50]!r}: {e}")
    print("✅ Gotovo.")


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
        comment(tracker, f"{owner_mention()}🔔 **Objavljeno: {iss['title']}** (#{n})\n{text}\n\n"
                         "Predaj TikTok i YouTube link na Vyro → kampanja → **Submit Post**.")
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
    m.add_argument("--hashtags", default="")
    m.add_argument("--clips", type=int, default=0)
    pb = sub.add_parser("publish")
    pb.add_argument("--issue", type=int, required=True)
    sub.add_parser("links")
    sub.add_parser("check")
    sub.add_parser("reschedule")
    sub.add_parser("daily")
    a = p.parse_args()
    if a.cmd == "make":
        cmd_make(a.url, a.max_videos, a.hashtags, a.clips)
    elif a.cmd == "daily":
        cmd_daily()
    elif a.cmd == "publish":
        cmd_publish(a.issue)
    elif a.cmd == "links":
        cmd_links()
    elif a.cmd == "reschedule":
        cmd_reschedule()
    else:
        cmd_check()


if __name__ == "__main__":
    main()
