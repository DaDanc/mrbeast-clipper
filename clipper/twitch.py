"""Twitch: popis klipova preko službenog Helix API-ja i skidanje klipa.

Treba GitHub secrete TWITCH_CLIENT_ID i TWITCH_CLIENT_SECRET (dev.twitch.tv/console).
Skidanje: yt-dlp; ako ne uspije, direktni mp4 link preko Twitch GQL-a (javni web klijent).
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import requests

HELIX = "https://api.twitch.tv/helix"
GQL = "https://gql.twitch.tv/gql"
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # javni ID Twitchove web stranice
CLIP_TOKEN_HASH = "36b89d2507fce29e5ca551df756d27c1cfe079e2609642b4390aa4c35796eb11"


class TwitchError(RuntimeError):
    pass


def _creds() -> tuple[str, str]:
    cid = os.environ.get("TWITCH_CLIENT_ID", "").strip()
    sec = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        raise TwitchError("Nedostaju secreti TWITCH_CLIENT_ID i/ili TWITCH_CLIENT_SECRET.")
    return cid, sec


@lru_cache(maxsize=None)
def _token() -> str:
    cid, sec = _creds()
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, data={
        "client_id": cid, "client_secret": sec, "grant_type": "client_credentials"})
    if r.status_code != 200:
        raise TwitchError(f"Twitch prijava nije uspjela ({r.status_code}): {r.text[:200]}")
    return r.json()["access_token"]


def helix(path: str, params: dict) -> dict:
    cid, _ = _creds()
    for attempt in range(4):
        r = requests.get(f"{HELIX}/{path}", params=params, timeout=30,
                         headers={"Client-Id": cid, "Authorization": f"Bearer {_token()}"})
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise TwitchError(f"Twitch API {path} greška {r.status_code}: {r.text[:200]}")
        return r.json()
    raise TwitchError(f"Twitch API {path} ne odgovara.")


@lru_cache(maxsize=None)
def user_id(login: str) -> str:
    data = helix("users", {"login": login}).get("data") or []
    if not data:
        raise TwitchError(f"Twitch korisnik '{login}' ne postoji.")
    return data[0]["id"]


def top_clips(login: str, days: int) -> list[dict]:
    """Klipovi zadnjih `days` dana, sortirani po broju pregleda (najviše prvo)."""
    now = datetime.now(timezone.utc)
    params = {
        "broadcaster_id": user_id(login),
        "started_at": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first": 100,
    }
    out: list[dict] = []
    for _ in range(3):  # do 300 klipova
        res = helix("clips", params)
        out.extend(res.get("data") or [])
        cursor = (res.get("pagination") or {}).get("cursor")
        if not cursor:
            break
        params["after"] = cursor
    out.sort(key=lambda c: c.get("view_count", 0), reverse=True)
    return out


def _slug(clip: dict) -> str:
    return clip.get("id") or clip["url"].rstrip("/").split("/")[-1]


def _gql_mp4_url(slug: str) -> str:
    body = {"operationName": "VideoAccessToken_Clip", "variables": {"slug": slug},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": CLIP_TOKEN_HASH}}}
    r = requests.post(GQL, json=body, headers={"Client-Id": GQL_CLIENT_ID}, timeout=30)
    r.raise_for_status()
    clip = (r.json().get("data") or {}).get("clip")
    if not clip or not clip.get("videoQualities"):
        raise TwitchError(f"GQL nije vratio video za klip {slug}")
    tok = clip["playbackAccessToken"]
    best = max(clip["videoQualities"], key=lambda q: float(q.get("quality") or 0))
    return f"{best['sourceURL']}?sig={tok['signature']}&token={urllib.parse.quote(tok['value'])}"


def download(clip: dict, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "best[ext=mp4]/best",
                        "-o", str(dest), clip["url"]], capture_output=True, text=True)
    if r.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000:
        return dest
    print(f"::warning::yt-dlp nije uspio ({r.stderr.strip()[-200:]}) – probam direktni link", flush=True)
    url = _gql_mp4_url(_slug(clip))
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                f.write(chunk)
    if dest.stat().st_size < 10_000:
        raise TwitchError(f"Skinuti klip je prazan: {clip['url']}")
    return dest
