"""Preuzima izvorni video kampanje.

Podržano:
  - Google Drive datoteka ili mapa (javni link "anyone with the link")
  - Dropbox link
  - direktan link na .mp4/.mov
  - YouTube link (preko yt-dlp; s GitHub servera ovo često ne radi jer YouTube blokira)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import requests

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _largest_videos(folder: Path, limit: int) -> list[Path]:
    vids = [p for p in folder.rglob("*") if p.suffix.lower() in VIDEO_EXT and p.is_file()]
    vids.sort(key=lambda p: p.stat().st_size, reverse=True)
    return vids[:limit]


def _download_direct(url: str, out_dir: Path) -> Path:
    name = re.sub(r"[^\w.-]", "_", url.split("?")[0].rstrip("/").split("/")[-1]) or "source.mp4"
    if Path(name).suffix.lower() not in VIDEO_EXT:
        name += ".mp4"
    out = out_dir / name
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype:
            raise RuntimeError(
                "Link vodi na web stranicu, a ne na video datoteku. "
                "Treba direktan link za preuzimanje ili javni Google Drive link."
            )
        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return out


def fetch(url: str, out_dir: Path, max_videos: int = 1) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = url.strip()

    if "drive.google.com" in url or "docs.google.com" in url:
        import gdown

        if "/folders/" in url:
            gdown.download_folder(url=url, output=str(out_dir), quiet=False, use_cookies=False)
        else:
            gdown.download(url=url, output=str(out_dir) + "/", quiet=False, fuzzy=True)
    elif "dropbox.com" in url:
        url = re.sub(r"([?&])dl=0", r"\1dl=1", url)
        if "dl=1" not in url:
            url += ("&" if "?" in url else "?") + "dl=1"
        _download_direct(url, out_dir)
    elif "youtube.com" in url or "youtu.be" in url:
        cmd = [
            "yt-dlp",
            "-f", "bv*[height<=1080]+ba/b[height<=1080]",
            "--merge-output-format", "mp4",
            "-o", str(out_dir / "%(id)s.%(ext)s"),
            url,
        ]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            raise RuntimeError(
                "YouTube je blokirao preuzimanje s GitHub servera (to je normalno). "
                "Uzmi materijal iz Vyro kampanje ili video stavi na svoj Google Drive "
                "i daj javni link."
            )
    else:
        _download_direct(url, out_dir)

    vids = _largest_videos(out_dir, max_videos)
    if not vids:
        raise RuntimeError("Nisam našao nijedan video u preuzetom materijalu.")
    return vids
