"""Stavlja gotov klip na Cloudinary da dobije javni, trajni link.

Buffer ne prima datoteke, nego samo javni URL videa koji mora raditi
sve dok se objava ne objavi. Cloudinary besplatni plan je dovoljan.
Treba GitHub secret CLOUDINARY_URL (izgleda kao cloudinary://KEY:SECRET@CLOUD_NAME).
"""
from __future__ import annotations

import os
from pathlib import Path


def upload(path: Path, public_id: str) -> str:
    import cloudinary
    import cloudinary.uploader

    if not os.environ.get("CLOUDINARY_URL"):
        raise RuntimeError("Nedostaje secret CLOUDINARY_URL (vidi upute, korak 3).")
    cloudinary.config(secure=True)
    res = cloudinary.uploader.upload_large(
        str(path),
        resource_type="video",
        public_id=public_id,
        folder="mrbeast-clips",
        overwrite=True,
        chunk_size=20_000_000,
    )
    url = res.get("secure_url")
    if not url:
        raise RuntimeError(f"Cloudinary upload nije vratio link: {res}")
    return url
