"""Sam pronalazi i skida epizode iz javne Frame.io mape kampanje.

Otvara mapu u pravom (headless) pregledniku, kao što bi to napravio čovjek,
pročita popis videa i za svaki "klikne" Download da dobije privremeni link.
"""
from __future__ import annotations

import re


def _seconds(text: str) -> int:
    """'55:12' ili '1:02:03' → sekunde."""
    parts = [int(p) for p in text.split(":")]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


def list_videos(share_url: str, min_minutes: int = 10) -> list[dict]:
    """Vrati [{name, seconds, url}] za sve dugačke videe (cijele epizode) u mapi."""
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        page.goto(share_url, wait_until="domcontentloaded", timeout=90_000)
        page.get_by_role("button", name=re.compile(r"Download Asset")).first.wait_for(timeout=90_000)
        page.wait_for_timeout(2000)

        buttons = page.get_by_role("button", name=re.compile(r"Download Asset"))
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            label = btn.get_attribute("aria-label") or btn.inner_text() or ""
            name = re.sub(r"\s*Download Asset\s*$", "", label).strip()
            # trajanje piše na kartici (npr. "55:12")
            card_text = btn.evaluate(
                "el => { let c = el; for (let k = 0; k < 8 && c; k++) {"
                " c = c.parentElement; if (c && /\\d+:\\d{2}/.test(c.innerText)) return c.innerText; }"
                " return ''; }"
            )
            m = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", card_text or "")
            secs = _seconds(m.group(1)) if m else 0
            if secs < min_minutes * 60:
                continue
            try:
                with page.expect_download(timeout=60_000) as dl:
                    btn.click()
                d = dl.value
                url = d.url
                d.cancel()
            except Exception as e:  # noqa: BLE001
                print(f"::warning::{name}: ne mogu dobiti link ({e})")
                continue
            out.append({"name": name, "seconds": secs, "url": url})
        browser.close()
    return out
