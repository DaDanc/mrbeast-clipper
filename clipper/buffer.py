"""Objavljivanje preko Buffer GraphQL API-ja (https://api.buffer.com).

Treba GitHub secret BUFFER_API_KEY (Buffer -> Settings -> API -> Create key).
Kanali se pronalaze sami: objavljuje se na svaki povezani TikTok/Instagram/YouTube
kanal koji je naveden u config.yaml -> platforms.
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

import requests

API = "https://api.buffer.com"

# Željene vrijednosti za posebna polja po mreži. Polja koja Buffer ne poznaje
# se automatski izbacuju (provjerava se shema API-ja), pa ovo ne može srušiti objavu.
PREFERRED_TYPE = {
    "youtube": ["short", "shorts", "video", "post"],
    "instagram": ["reel", "reels", "post"],
    "tiktok": ["video", "post"],
}
DEFAULTS = {
    "youtube": {
        "categoryId": "24",  # Entertainment
        "privacy": "public",
        "license": "youtube",
        "madeForKids": False,
        "notifySubscribers": True,
        "embeddable": True,
        "isAiGenerated": False,
    },
    "instagram": {"shouldShareToFeed": True, "isAiGenerated": False},
    "tiktok": {"isAiGenerated": False},
}


class BufferError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("BUFFER_API_KEY", "").strip()
    if not k:
        raise BufferError("Nedostaje secret BUFFER_API_KEY (vidi upute, korak 2).")
    return k


def gql(query: str, variables: dict | None = None) -> dict:
    for attempt in range(4):
        r = requests.post(
            API,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"},
            timeout=60,
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "30"))
            if wait > 120:
                raise BufferError(f"Buffer API limit dosegnut, pokušaj za {wait // 60} min.")
            time.sleep(wait)
            continue
        if r.status_code == 401:
            raise BufferError("Buffer API ključ ne valja (401). Napravi novi i zamijeni secret.")
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise BufferError("; ".join(e.get("message", str(e)) for e in body["errors"]))
        return body["data"]
    raise BufferError("Buffer API ne odgovara nakon više pokušaja.")


@lru_cache(maxsize=None)
def get_org_id() -> str:
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    if not orgs:
        raise BufferError("Buffer račun nema nijednu organizaciju.")
    return orgs[0]["id"]


def get_channels(services: list[str]) -> list[dict]:
    org = get_org_id()
    chans = gql(
        """query($org: OrganizationId!) {
             channels(input: { organizationId: $org }) {
               id name service isLocked isDisconnected
             }
           }""",
        {"org": org},
    )["channels"]
    wanted = {s.lower() for s in services}
    out = [c for c in chans if c["service"].lower() in wanted and not c["isLocked"] and not c["isDisconnected"]]
    return out


@lru_cache(maxsize=None)
def _input_fields(type_name: str) -> dict | None:
    """Vraća {ime_polja: {"required": bool, "enum": [..] ili None, "kind": str}} ili None."""
    q = """query($n: String!) {
      __type(name: $n) {
        inputFields { name type { kind name enumValues { name }
          ofType { kind name enumValues { name } ofType { kind name } } } }
      }
    }"""
    try:
        t = gql(q, {"n": type_name})["__type"]
    except Exception:
        return None
    if not t:
        return None
    fields = {}
    for f in t["inputFields"] or []:
        ty = f["type"]
        required = ty["kind"] == "NON_NULL"
        base = ty["ofType"] if required else ty
        enum = [e["name"] for e in (base.get("enumValues") or [])] or None
        fields[f["name"]] = {"required": required, "enum": enum, "kind": base["kind"], "type": base.get("name")}
    return fields


def _meta_type_name(service: str) -> str:
    return {
        "youtube": "YoutubePostMetadataInput",
        "instagram": "InstagramPostMetadataInput",
        "tiktok": "TikTokPostMetadataInput",
    }[service]


def build_metadata(service: str, yt_title: str) -> dict | None:
    service = service.lower()
    if service not in DEFAULTS:
        return None
    wanted = dict(DEFAULTS[service])
    if service == "youtube":
        wanted["title"] = yt_title[:100]

    fields = _input_fields(_meta_type_name(service))
    if fields is None:  # shema nedostupna - sigurna minimalna verzija
        if service == "instagram":
            return {"instagram": {"type": "reel", "shouldShareToFeed": True}}
        if service == "youtube":
            return {"youtube": {"title": yt_title[:100], "categoryId": "24"}}
        return None

    meta: dict = {}
    for name, info in fields.items():
        if name == "type" and info["enum"]:
            pick = next((p for p in PREFERRED_TYPE.get(service, []) if p in info["enum"]), None)
            if pick or info["required"]:
                meta["type"] = pick or info["enum"][0]
            continue
        if name in wanted:
            val = wanted[name]
            if info["enum"] and val not in info["enum"]:
                val = next((e for e in info["enum"] if e.lower() == str(val).lower()), info["enum"][0])
            meta[name] = val
        elif name == "category" and info["kind"] == "INPUT_OBJECT":
            meta["category"] = {"categoryId": "24", "title": "Entertainment"}
        elif info["required"] and info["enum"]:
            meta[name] = info["enum"][0]
    return {service: meta} if meta else None


CREATE = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id status dueAt } }
    ... on MutationError { message }
  }
}"""


def create_video_post(channel: dict, text: str, video_url: str, yt_title: str,
                      mode: str = "shareNow", due_at: str | None = None) -> dict:
    service = channel["service"].lower()
    inp = {
        "channelId": channel["id"],
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled" if due_at else mode,
        "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": 1500}}}],
    }
    if due_at:
        inp["dueAt"] = due_at
    meta = build_metadata(service, yt_title)
    if meta:
        inp["metadata"] = meta
    if service == "youtube":  # thumbnailOffset podržan samo za IG/TikTok/Pinterest
        inp["assets"] = [{"video": {"url": video_url}}]
    res = gql(CREATE, {"input": inp})["createPost"]
    if "post" not in res:
        raise BufferError(res.get("message", str(res)))
    return res["post"]


def scheduled_posts(channel_id: str) -> list[dict]:
    """Objave koje na kanalu čekaju objavu: [{id, dueAt, text}]."""
    res = gql(
        """query($org: OrganizationId!, $ch: [ChannelId!]) {
             posts(first: 100, input: { organizationId: $org,
                   filter: { status: [scheduled], channelIds: $ch },
                   sort: [{ field: dueAt, direction: asc }] }) {
               edges { node { id dueAt text } }
             }
           }""",
        {"org": get_org_id(), "ch": [channel_id]},
    )["posts"]
    return [e["node"] for e in (res.get("edges") or []) if e["node"].get("dueAt")]


def set_post_time(post_id: str, due_at: str) -> dict:
    res = gql(
        """mutation($input: EditPostInput!) {
             editPost(input: $input) {
               ... on PostActionSuccess { post { id dueAt } }
               ... on MutationError { message }
             }
           }""",
        {"input": {"id": post_id, "mode": "customScheduled", "dueAt": due_at}},
    )["editPost"]
    if "post" not in res:
        raise BufferError(res.get("message", str(res)))
    return res["post"]


def get_post(post_id: str) -> dict:
    return gql(
        """query($id: PostId!) {
             post(input: { id: $id }) { id status externalLink sentAt channelService error { message } }
           }""",
        {"id": post_id},
    )["post"]
