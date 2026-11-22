"""Twitch → TikTok clipper. Pokreću ga GitHub Actions workflowi.

  python -m clipper.main gate                 -> je li sad vrijeme za objavu (ispisuje termin)
  python -m clipper.main run --termin T       -> odaberi klip, montiraj, pošalji u Buffer za termin T
  python -m clipper.main run --test 3         -> napravi 3 videa u mapu out/ (bez objave)
  python -m clipper.main links                -> obavijest kad je klip objavljen + pregledi
  python -m clipper.main check                -> provjeri Twitch, Buffer i Cloudinary
  python -m clipper.main fail --run-url URL   -> obavijest da run nije uspio
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STATE = ROOT / "posted.json"
WORK = ROOT / "work"
ERROR_FILE = WORK / "greska.txt"
TRACKER_TITLE = "📋 Objave na TikToku"
OLD_TRACKER_TITLES = ["📋 Linkovi za Vyro"]
TZ = ZoneInfo(CFG.get("vremenska_zona", "Europe/Zagreb"))


# ---------------------------------------------------------------- stanje (posted.json)
def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"objavljeno": []}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- GitHub obavijesti
def gh(*args: str) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} nije uspio: {res.stderr.strip()}")
    return (res.stdout or "").strip()


def owner_mention() -> str:
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    return f"@{owner} " if owner else ""


def tracker_issue() -> int:
    """Pinani Issue u koji idu obavijesti (stari "Linkovi za Vyro" se preimenuje)."""
    found = json.loads(gh("issue", "list", "--state", "open", "--limit", "100", "--json", "number,title"))
    for i in found:
        if i["title"] == TRACKER_TITLE:
            return i["number"]
    body = ("Ovdje stižu obavijesti clippera: 🔔 objavljen klip (s linkom), 🚀 pregledi, ❌ greške.\n"
            "Postavke su u `config.json`.\n")
    for i in found:
        if i["title"] in OLD_TRACKER_TITLES:
            gh("issue", "edit", str(i["number"]), "--title", TRACKER_TITLE, "--body", body)
            return i["number"]
    url = gh("issue", "create", "--title", TRACKER_TITLE, "--body", body)
    num = int(url.rstrip("/").split("/")[-1])
    subprocess.run(["gh", "issue", "pin", str(num)], capture_output=True)
    return num


def notify(body: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    gh("issue", "comment", str(tracker_issue()), "--body-file", f.name)


# ---------------------------------------------------------------- termini
def _hm(s: str) -> int:
    hh, mm = (int(x) for x in s.split(":"))
    return hh * 60 + mm


def random_times(n: int, start_min: int, end_min: int, gap: int, seed: str) -> list[int]:
    """n nasumičnih minuta u danu između start i end, međusobno barem `gap` min razmaka.
    Isti seed → uvijek ista vremena. Ako ne stane, razmak se smanjuje."""
    rng = random.Random(seed)
    while gap >= 0:
        for _ in range(2000):
            ts = sorted(rng.randint(start_min, end_min) for _ in range(n))
            if all(b - a >= gap for a, b in zip(ts, ts[1:])):
                return ts
        gap = gap // 2 if gap > 10 else gap - 10
    return sorted(rng.randint(start_min, end_min) for _ in range(n))


def day_slots(d) -> list[datetime]:
    """Termini objava za dan d: `objave_dnevno` nasumičnih vremena u `prozor_objava` (svaki dan druga)."""
    od, do = CFG.get("prozor_objava") or ["12:00", "23:30"]
    ts = random_times(int(CFG.get("objave_dnevno", 3)), _hm(od), _hm(do),
                      int(CFG.get("min_razmak_minuta", 120)), f"termini-{d.isoformat()}")
    return [datetime(d.year, d.month, d.day, t // 60, t % 60, tzinfo=TZ) for t in ts]


def _slots_around(now: datetime) -> list[datetime]:
    out = []
    for day in (-1, 0, 1, 2):
        out += day_slots((now + timedelta(days=day)).date())
    return sorted(out)


def slot_key(slot: datetime) -> str:
    return slot.strftime("%Y-%m-%d %H:%M")


def due_time(slot: datetime, now: datetime) -> datetime:
    """Vrijeme objave = termin (već nasumičan), ali najranije za 10 min."""
    return max(slot, now + timedelta(minutes=10)).replace(second=0, microsecond=0)


def posts_on(day, state: dict) -> int:
    return sum(1 for e in state["objavljeno"]
               if datetime.fromisoformat(e["zakazano"]).astimezone(TZ).date() == day)


def cmd_gate(manual: bool) -> None:
    """Zakazani run (svaki sat): termin koji je za 0-75 min (ili do 20 min prošao, ako GitHub kasni).
    Ručni run: sljedeći slobodan termin. Dan koji već ima `objave_dnevno` objava se preskače.
    Ispisuje termin u GITHUB_OUTPUT (prazno = ništa)."""
    now = datetime.now(TZ)
    state = load_state()
    taken = {e.get("termin") for e in state["objavljeno"]}
    per_day = int(CFG.get("objave_dnevno", 3))
    print("Današnji termini: " + ", ".join(f"{s:%H:%M}" for s in day_slots(now.date())))
    pick = ""
    for s in _slots_around(now):
        if slot_key(s) in taken or posts_on(s.date(), state) >= per_day:
            continue
        diff = (s - now).total_seconds() / 60
        if (manual and diff > 5) or (-20 <= diff <= 75):
            pick = slot_key(s)
            break
    print(f"Sad je {now:%d.%m. %H:%M} → termin: {pick or 'nijedan (ništa ne radim)'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"termin={pick}\n")


# ---------------------------------------------------------------- odabir klipova
def _blocked(title: str) -> bool:
    words = set(re.findall(r"[a-z]+", title.lower()))
    return bool(words & {w.lower() for w in CFG.get("blokirane_rijeci") or []})


def candidates(streamer: dict, posted_ids: set[str]) -> list[dict]:
    from . import twitch
    from .render import clean_title

    clips = twitch.top_clips(streamer["login"], int(CFG.get("dana_unazad", 7)))
    lang = str(CFG.get("jezik", "en")).lower()
    lo, hi = float(CFG.get("min_sekundi", 10)), float(CFG.get("max_sekundi", 60))
    out, why = [], {}
    for c in clips:
        reason = None
        if c["id"] in posted_ids:
            reason = "već objavljen"
        elif not (lo <= float(c.get("duration") or 0) <= hi):
            reason = "trajanje"
        elif not str(c.get("language") or "").lower().startswith(lang):
            reason = "jezik"
        elif int(c.get("view_count") or 0) < int(streamer.get("min_pregleda", 0)):
            reason = "premalo pregleda"
        elif _blocked(c.get("title") or ""):
            reason = "zabranjena riječ u naslovu"
        elif not clean_title(c.get("title") or "", int(CFG.get("hook_max_rijeci", 6))):
            reason = "naslov neupotrebljiv za hook"
        if reason:
            why[reason] = why.get(reason, 0) + 1
            continue
        c["_streamer"] = streamer
        out.append(c)
    print(f"▶ {streamer['login']}: {len(clips)} klipova u zadnjih {CFG.get('dana_unazad', 7)} dana, "
          f"{len(out)} prolazi filtere. Odbijeno: {why or '-'}", flush=True)
    return out


# ---------------------------------------------------------------- izrada videa
def make_video(clip: dict, workdir: Path) -> tuple[Path, str]:
    """Skini + titlovi + montaža. Vraća (gotov mp4, hook tekst)."""
    from . import render, transcribe, twitch

    st = clip["_streamer"]
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"▶ Klip: [{st['login']}] {clip['title']!r} ({clip['view_count']} pregleda, "
          f"{clip['duration']:.0f} s) {clip['url']}", flush=True)
    src = twitch.download(clip, workdir / "src.mp4")
    dur = render.probe_duration(src)
    wav = transcribe.extract_audio(src, workdir / "audio.wav")
    segs = transcribe.transcribe(wav, CFG.get("whisper_model", "small"))
    hook = render.clean_title(clip["title"], int(CFG.get("hook_max_rijeci", 6)))
    layout = "B" if st.get("facecam") else "A"
    ass = render.build_ass(segs, dur, hook, float(CFG.get("hook_sekundi", 2.8)), layout, workdir / "subs.ass")
    out = workdir / f"{st['login']}_{clip['id'][:40]}.mp4"
    render.render(src, ass, out, layout, st.get("facecam"))
    print(f"   ✅ gotovo: {out.name} ({out.stat().st_size / 1e6:.1f} MB, varijanta {layout}, hook {hook!r})",
          flush=True)
    return out, hook


def caption(clip: dict, hook: str) -> str:
    st = clip["_streamer"]
    h = hook if hook != hook.lower() else hook[:1].upper() + hook[1:]
    return CFG["opis_posta"].format(hook=h, login=st["login"], ime=st.get("ime", st["login"]),
                                    hashtagovi=st.get("hashtagovi", "")).strip()


# ---------------------------------------------------------------- run
def cmd_run(termin: str, test: int) -> None:
    state = load_state()
    posted_ids = {e["id"] for e in state["objavljeno"]}
    per_streamer, api_errors = [], []
    for st in CFG["streameri"]:
        try:
            per_streamer.append(candidates(st, posted_ids))
        except Exception as e:  # Twitch greška za jednog streamera – probaj ostale
            print(f"::warning::{st['login']}: {e}")
            api_errors.append(f"{st['login']}: {e}")
            per_streamer.append([])
    if api_errors and not any(per_streamer):
        raise RuntimeError("Twitch API greška:\n" + "\n".join(api_errors))

    if test:
        return _run_test(per_streamer, test)

    queue = [c for lst in per_streamer for c in lst]   # prvo glavni streamer, pa rezerva
    if not queue:
        raise RuntimeError("Nema nijednog klipa koji prolazi filtere (svi streameri, zadnjih "
                           f"{CFG.get('dana_unazad', 7)} dana).")
    now = datetime.now(TZ)
    slot = datetime.strptime(termin, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    if termin in {e.get("termin") for e in state["objavljeno"]}:
        print(f"Termin {termin} već ima objavu – ništa ne radim.")
        return
    errors = []
    for clip in queue[:3]:   # ako montaža jednog klipa pukne, probaj sljedeći
        try:
            video, hook = make_video(clip, WORK / clip["id"][:40])
        except Exception as e:
            errors.append(f"{clip['url']}: {e}")
            print(f"::warning::Klip nije uspio: {e}")
            continue
        return _publish(clip, video, hook, slot, now, state)
    raise RuntimeError("Montaža nije uspjela ni za jedan klip:\n" + "\n".join(errors))


def cmd_publish_ids(ids: list[str]) -> None:
    """Ručno: objavi točno ove Twitch klipove (ID-jevi) DANAS, u nasumična vremena do kraja prozora."""
    from . import twitch

    state = load_state()
    ids = [i for i in ids if i and i not in {e["id"] for e in state["objavljeno"]}]
    if not ids:
        print("Svi navedeni klipovi su već objavljeni.")
        return
    by_id = {str(twitch.user_id(st["login"])): st for st in CFG["streameri"]}
    clips = twitch.clips_by_id(ids)
    missing = set(ids) - {c["id"] for c in clips}
    if missing:
        raise RuntimeError(f"Twitch ne zna za klipove: {', '.join(missing)}")
    now = datetime.now(TZ)
    _, end = CFG.get("prozor_objava") or ["12:00", "23:30"]
    start_min = now.hour * 60 + now.minute + 25          # prvi najranije za ~25 min (montaža traje)
    end_min = max(_hm(end), start_min + 30 * len(clips))
    times = random_times(len(clips), start_min, min(end_min, 23 * 60 + 55),
                         int(CFG.get("min_razmak_minuta", 120)), f"rucno-{now.isoformat()}")
    for clip, t in zip(sorted(clips, key=lambda c: ids.index(c["id"])), times):
        clip["_streamer"] = by_id.get(str(clip["broadcaster_id"])) or \
            {"login": clip["broadcaster_name"].lower(), "ime": clip["broadcaster_name"], "hashtagovi": "#twitch #fyp"}
        slot = now.replace(hour=t // 60, minute=t % 60, second=0, microsecond=0)
        video, hook = make_video(clip, WORK / clip["id"][:40])
        _publish(clip, video, hook, slot, datetime.now(TZ), state)


def _run_test(per_streamer: list[list[dict]], n: int) -> None:
    """Test: N videa bez objave. Ako ima rezervnog streamera, zadnji video je njegov (da se vide obje varijante)."""
    picks = per_streamer[0][: n - 1] if len(per_streamer) > 1 and per_streamer[1] else per_streamer[0][:n]
    for lst in per_streamer[1:]:
        picks += lst[: n - len(picks)]
    picks += [c for c in per_streamer[0] if c not in picks][: n - len(picks)]
    if not picks:
        raise RuntimeError("Nema nijednog klipa koji prolazi filtere.")
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    summary = []
    for k, clip in enumerate(picks, 1):
        video, hook = make_video(clip, WORK / clip["id"][:40])
        dest = out_dir / f"{k}_{video.name}"
        video.replace(dest)
        for t in (1.0, float(clip["duration"]) * 0.6):  # sličice za brzi pregled
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.1f}", "-i", str(dest),
                            "-frames:v", "1", "-vf", "scale=540:-2", str(dest.with_suffix(f".{int(t)}s.jpg"))])
        summary.append(f"=== {dest.name}\nID: {clip['id']}\nTwitch: {clip['url']} ({clip['view_count']} pregleda)\n"
                       f"Opis posta:\n{caption(clip, hook)}\n")
    (out_dir / "opisi.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))


def _publish(clip: dict, video: Path, hook: str, slot: datetime, now: datetime, state: dict) -> None:
    from . import buffer, hosting

    st = clip["_streamer"]
    text = caption(clip, hook)
    url = hosting.upload(video, f"{st['login']}-{clip['id'][:60]}")
    due = due_time(slot, now)
    channels = buffer.get_channels(CFG["platforme"])
    if not channels:
        raise RuntimeError(f"U Bufferu nema povezanih kanala za: {', '.join(CFG['platforme'])}.")
    posts, errs = {}, []
    for ch in channels:
        try:
            p = buffer.create_video_post(ch, text, url, hook or st.get("ime", ""), "customScheduled",
                                         due_at=due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            posts[p["id"]] = ch["service"]
            print(f"::notice::{ch['service']} ({ch['name']}): zakazano za {due:%d.%m. %H:%M}")
        except Exception as e:
            errs.append(f"{ch['service']}: {e}")
    if not posts:
        raise RuntimeError("Buffer nije prihvatio objavu: " + "; ".join(errs))
    state["objavljeno"].append({
        "id": clip["id"], "streamer": st["login"], "naslov": clip["title"], "hook": hook,
        "twitch": clip["url"], "pregleda_twitch": clip["view_count"], "termin": slot_key(slot),
        "zakazano": due.isoformat(), "video": url, "buffer": posts, "link": None,
        "obavijest": False, "pregledi_obavijesti": [],
    })
    save_state(state)
    if errs:
        print("::warning::" + "; ".join(errs))


# ---------------------------------------------------------------- links / pregledi
def _tiktok_views(url: str) -> int | None:
    try:
        res = subprocess.run(["yt-dlp", "--dump-single-json", "--skip-download", "--no-warnings", url],
                             capture_output=True, text=True, timeout=90)
        if res.returncode == 0:
            v = json.loads(res.stdout).get("view_count")
            if v is not None:
                return int(v)
    except Exception:
        pass
    return None


def cmd_links() -> None:
    from . import buffer

    state = load_state()
    changed = False
    for e in state["objavljeno"]:
        if e.get("obavijest"):
            continue
        lines, finished = [], True
        for pid, service in (e.get("buffer") or {}).items():
            try:
                p = buffer.get_post(pid)
            except Exception as ex:
                lines.append(f"- {service}: ne mogu provjeriti ({ex})")
                continue
            status = str(p.get("status") or "").lower()
            if p.get("externalLink"):
                lines.append(f"- **{service}**: {p['externalLink']}")
                if service.lower() == "tiktok":
                    e["link"] = p["externalLink"]
            elif status == "error" or p.get("error"):
                lines.append(f"- ❌ **{service}**: objava nije uspjela – {(p.get('error') or {}).get('message', '?')}")
            elif status == "sent":
                lines.append(f"- **{service}**: objavljeno (Buffer nije vratio link)")
            else:
                finished = False
        if not finished:
            print(f"{e['id']}: još čeka objavu ({e.get('zakazano')}).")
            continue
        failed = any("❌" in l for l in lines)
        ping = owner_mention() if (failed or CFG.get("obavijest_za_svaku_objavu")) else ""
        icon = "❌ **Objava nije uspjela**" if failed else "🔔 **Objavljeno**"
        notify(f"{ping}{icon}: {e.get('hook') or e['naslov']} ({e['streamer']})\n"
               + "\n".join(lines or ["- (nema objava)"]) + f"\n\nTwitch klip: {e['twitch']}")
        e["obavijest"] = True
        changed = True

    limits = sorted(int(x) for x in (CFG.get("obavijest_pregledi") or []))
    cutoff = datetime.now(TZ) - timedelta(days=int(CFG.get("prati_dana", 7)))
    for e in state["objavljeno"]:
        if not e.get("link") or not limits or datetime.fromisoformat(e["zakazano"]) < cutoff:
            continue
        views = _tiktok_views(e["link"])
        if views is None:
            continue
        done = set(e.get("pregledi_obavijesti") or [])
        new = [l for l in limits if views >= l and l not in done]
        print(f"{e['link']}: {views} pregleda")
        if new:
            e["pregledi_obavijesti"] = sorted(done | set(new))
            notify(f"{owner_mention()}🚀 **TikTok klip je prešao {max(new):,} pregleda** ({views:,}) – "
                   f"{e.get('hook') or e['naslov']}\n{e['link']}")
            changed = True
    if changed:
        save_state(state)


# ---------------------------------------------------------------- check / fail
def cmd_check() -> None:
    from . import buffer, twitch

    ok = True
    print("▶ Twitch API...")
    for st in CFG["streameri"]:
        try:
            n = len(twitch.top_clips(st["login"], int(CFG.get("dana_unazad", 7))))
            print(f"  ✅ {st['login']}: {n} klipova u zadnjih {CFG.get('dana_unazad', 7)} dana")
        except Exception as e:
            print(f"  ❌ {st['login']}: {e}")
            ok = False
    print("▶ Buffer...")
    try:
        chans = buffer.get_channels(CFG["platforme"])
        for c in chans:
            waiting = buffer.scheduled_posts(c["id"])
            print(f"  ✅ {c['service']}: {c['name']} – {len(waiting)} objava čeka u redu")
            for p in waiting:
                print(f"       {p['dueAt']}  {(p.get('text') or '')[:60]!r}")
        if not chans:
            print(f"  ❌ nema povezanih kanala za {CFG['platforme']}")
            ok = False
    except Exception as e:
        print(f"  ❌ {e}")
        ok = False
    print("▶ Cloudinary...")
    try:
        import cloudinary
        import cloudinary.api
        cloudinary.config(secure=True)
        cloudinary.api.ping()
        print("  ✅ radi")
    except Exception as e:
        print(f"  ❌ {e}")
        ok = False
    print("\n✅ SVE SPREMNO" if ok else "\n❌ Nešto ne valja – pogledaj gore.")
    sys.exit(0 if ok else 1)


def cmd_fail(run_url: str, what: str) -> None:
    reason = ERROR_FILE.read_text(encoding="utf-8").strip() if ERROR_FILE.exists() else \
        "greška izvan programa (instalacija, Buffer/Cloudinary, git) – pogledaj log"
    notify(f"{owner_mention()}❌ **{what} nije uspio**\n\n```\n{reason[-1500:]}\n```\n\nLog: {run_url}")


def cmd_ocisti(contains: str) -> None:
    """Obriši iz Buffer reda zakazane objave čiji tekst sadrži `contains`."""
    from . import buffer

    n = 0
    for ch in buffer.get_channels(CFG["platforme"]):
        for p in buffer.scheduled_posts(ch["id"]):
            if contains.lower() in (p.get("text") or "").lower():
                buffer.delete_post(p["id"])
                n += 1
                print(f"::notice::Obrisano iz Buffera ({ch['service']}, {p['dueAt']}): {(p.get('text') or '')[:60]!r}")
    print(f"Obrisano {n} objava.")


# ---------------------------------------------------------------- main
def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--manual", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--termin", default="")
    r.add_argument("--test", type=int, default=0)
    r.add_argument("--ids", default="", help="Twitch ID-jevi klipova odvojeni zarezom → objava danas")
    o = sub.add_parser("ocisti")
    o.add_argument("--sadrzi", required=True)
    sub.add_parser("links")
    sub.add_parser("check")
    f = sub.add_parser("fail")
    f.add_argument("--run-url", default="")
    f.add_argument("--what", default="Run")
    a = p.parse_args()

    WORK.mkdir(exist_ok=True)
    try:
        if a.cmd == "gate":
            cmd_gate(a.manual)
        elif a.cmd == "run":
            if a.ids.strip():
                cmd_publish_ids([x.strip() for x in a.ids.replace(" ", ",").split(",") if x.strip()])
            elif not a.test and not a.termin:
                raise SystemExit("Treba --termin, --ids ili --test.")
            else:
                cmd_run(a.termin, a.test)
        elif a.cmd == "ocisti":
            cmd_ocisti(a.sadrzi)
        elif a.cmd == "links":
            cmd_links()
        elif a.cmd == "check":
            cmd_check()
        elif a.cmd == "fail":
            cmd_fail(a.run_url, a.what)
    except Exception as e:
        if a.cmd != "fail":
            ERROR_FILE.write_text(f"{type(e).__name__}: {e}\n\n" + "".join(traceback.format_exc()[-1200:]),
                                  encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
