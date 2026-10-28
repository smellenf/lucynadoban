#!/usr/bin/env python3
"""Keep the Songs list on index.html in step with Lucy's YouTube channel.

- Adds videos that are new on the channel (newest first), with a thumbnail.
- Removes videos that YouTube says no longer exist.
- Never touches text already on the site (titles, credits, venues), and never
  re-adds a video marked "hidden": true.
"""
import json, os, re, sys, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime

CHANNEL_ID = "UC6gDByjwNEIzdHpB_CZJIpw"
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE = os.path.join(ROOT, "index.html")
THUMBS = os.path.join(ROOT, "thumbs")
UA = {"User-Agent": "Mozilla/5.0 (lucynadoban.com sync)"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
BLOCK = re.compile(r"(  var SONGS = \[\n)(.*?)(\n  \];\n  /\* SONGS:END \*/)", re.S)
DATE_RX = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(,)?\s+\d{4}\b", re.I)


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def status_of(url):
    try:
        return get(url)[0]
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def fmt_date(d):
    return f"{d:%b} {d.day}, {d.year}"


def parse_title(raw, published):
    parts = [p.strip() for p in re.split(r"\s+-\s+", raw) if p.strip()]
    artist = [p for p in parts if re.search(r"\blucy\b", p, re.I)]
    rest = [p for p in parts if p not in artist]
    others = []
    for a in artist:
        names = re.split(r"\s*(?:&|\band\b|,)\s*", a)
        others += [n for n in names if n and not re.search(r"\blucy\b", n, re.I)]
    title = rest[0] if rest else raw
    when, where = fmt_date(published), []
    for p in rest[1:]:
        p = DATE_RX.sub("", p).strip(" ,")  # dates in titles are dropped; upload date is used
        if p:
            where.append(p)
    entry = {
        "title": title,
        "orig": False,
        "when": when,
        "dur": "",
        "where": " · ".join(where),
        "note": ("With " + " and ".join(others) + ".") if others else "",
    }
    # Songs with Paloma Toll are Coreadon songs, co-written by the two of them.
    if any(re.search(r"\bpaloma\b", o, re.I) for o in others):
        rest_names = [o for o in others if not re.search(r"\bpaloma\b", o, re.I)]
        entry["orig"] = True
        entry["band"] = "Coreadon"
        entry["note"] = "Co-written and performed with Paloma Toll." + (
            " With " + " and ".join(rest_names) + "." if rest_names else "")
    return entry


def duration(video_id):
    try:
        _, html = get(f"https://www.youtube.com/watch?v={video_id}")
        m = re.search(rb'"lengthSeconds":"(\d+)"', html)
        if m:
            s = int(m.group(1))
            return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    except Exception:
        pass
    return ""


def save_thumb(video_id):
    os.makedirs(THUMBS, exist_ok=True)
    for size in ("maxresdefault", "hqdefault"):
        try:
            code, data = get(f"https://i.ytimg.com/vi/{video_id}/{size}.jpg")
            if code == 200 and len(data) > 2000:
                path = os.path.join(THUMBS, f"{video_id}.jpg")
                try:
                    from PIL import Image
                    import io
                    im = Image.open(io.BytesIO(data)).convert("RGB")
                    im.thumbnail((960, 540))
                    im.save(path, quality=82, optimize=True)
                except Exception:
                    open(path, "wb").write(data)
                return True
        except Exception:
            continue
    return False


def main():
    page = open(PAGE, encoding="utf-8").read()
    m = BLOCK.search(page)
    if not m:
        sys.exit("SONGS block not found in index.html")
    songs = json.loads("[" + m.group(2) + "]")
    known = {s["id"] for s in songs}

    _, xml = get(FEED)
    feed = []
    for e in ET.fromstring(xml).findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        title = e.findtext("a:title", namespaces=NS) or ""
        pub = datetime.fromisoformat(e.findtext("a:published", namespaces=NS).replace("Z", "+00:00"))
        feed.append((vid, title, pub))
    if not feed:
        sys.exit("Feed came back empty; not changing anything.")
    feed_ids = {v for v, _, _ in feed}

    added = []
    for vid, title, pub in feed:  # feed is newest first
        if vid in known:
            continue
        entry = {"id": vid, **parse_title(title, pub)}
        entry["dur"] = duration(vid)
        save_thumb(vid)
        added.append(entry)

    removed = []
    keep = []
    for s in songs:
        if s["id"] not in feed_ids and status_of(
                f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={s['id']}") == 404:
            removed.append(s)
            t = os.path.join(THUMBS, f"{s['id']}.jpg")
            if os.path.exists(t):
                os.remove(t)
        else:
            keep.append(s)

    if not added and not removed:
        print("No changes.")
        return
    new = added + keep
    body = ",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in new)
    page = page[:m.start(2)] + body + page[m.end(2):]
    open(PAGE, "w", encoding="utf-8").write(page)
    for s in added:
        print(f"Added: {s['title']} ({s['id']})")
    for s in removed:
        print(f"Removed: {s['title']} ({s['id']})")


if __name__ == "__main__":
    main()
