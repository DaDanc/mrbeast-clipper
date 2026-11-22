"""Privremena proba: radi li skidanje Twitch klipova s GitHub servera + frameovi za facecam."""
import json, subprocess, sys, urllib.parse
from pathlib import Path
import requests

GQL = "https://gql.twitch.tv/gql"
CID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
out = Path("probe"); out.mkdir(exist_ok=True)

def clips(login, n=12):
    for crit in ("{period:LAST_WEEK,sort:VIEWS_DESC}", "{filter:LAST_WEEK}", "{period:LAST_WEEK}"):
        q = "query($l:String!){user(login:$l){clips(first:%d,criteria:%s){edges{node{id slug title viewCount durationSeconds language url}}}}}" % (n, crit)
        r = requests.post(GQL, json={"query": q, "variables": {"l": login}}, headers={"Client-Id": CID}, timeout=30)
        j = r.json()
        try:
            return [e["node"] for e in j["data"]["user"]["clips"]["edges"]]
        except Exception:
            print("GQL", crit, json.dumps(j)[:600])
    sys.exit(1)

def gql_url(slug):
    body = {"operationName": "VideoAccessToken_Clip", "variables": {"slug": slug},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "36b89d2507fce29e5ca551df756d27c1cfe079e2609642b4390aa4c35796eb11"}}}
    c = requests.post(GQL, json=body, headers={"Client-Id": CID}, timeout=30).json()["data"]["clip"]
    tok = c["playbackAccessToken"]
    best = max(c["videoQualities"], key=lambda q: float(q["quality"]))
    return best["sourceURL"] + "?sig=" + tok["signature"] + "&token=" + urllib.parse.quote(tok["value"])

for login in ["jynxzi", "caseoh_"]:
    cs = clips(login)
    print(f"== {login}: {len(cs)} klipova")
    for c in cs:
        print(f"   {c['viewCount']:>8} {c['durationSeconds']:>5}s {c['language']} {c['slug'][:40]} | {c['title']}")
    for k, c in enumerate(cs[:6]):
        f = out / f"{login}_{k}.mp4"
        r = subprocess.run(["yt-dlp", "-q", "-o", str(f), c["url"]], capture_output=True, text=True)
        how = "yt-dlp"
        if r.returncode != 0 or not f.exists():
            print(f"   yt-dlp FAIL {c['slug']}: {r.stderr[-300:]}")
            how = "gql"
            try:
                data = requests.get(gql_url(c["slug"]), timeout=60).content
                f.write_bytes(data)
            except Exception as e:
                print(f"   gql FAIL: {e}"); continue
        # i GQL test posebno
        if k == 0:
            try:
                u = gql_url(c["slug"]); sz = len(requests.get(u, timeout=60).content)
                print(f"   GQL direktni link radi: {sz} B")
            except Exception as e:
                print(f"   GQL direktni link FAIL: {e}")
        print(f"   OK ({how}) {f} {f.stat().st_size} B")
        for p in (0.2, 0.5, 0.8):
            t = c["durationSeconds"] * p
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.1f}", "-i", str(f), "-frames:v", "1",
                            "-vf", "scale=960:-2", str(out / f"{login}_{k}_{int(p*100)}.jpg")])
        f.unlink()
