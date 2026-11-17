"""Collect candidate articles from RSS feeds and Hacker News."""
import calendar
import time
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests

UA = {"User-Agent": "sysdigest/1.0 (personal reading digest)"}


def normalize(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))


def from_feeds(feeds, max_age_days):
    cutoff = time.time() - max_age_days * 86400
    for feed in feeds:
        try:
            resp = requests.get(feed["url"], headers=UA, timeout=20)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as e:
            print(f"  ! {feed['name']}: {e}")
            continue
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = calendar.timegm(ts) if ts else time.time()
            if published < cutoff or not e.get("link"):
                continue
            yield {
                "title": e.get("title", "").strip(),
                "url": normalize(e["link"]),
                "summary": e.get("summary", ""),
                "source": feed["name"],
                "published": published,
                "points": 0,
            }


def from_hackernews(cfg, max_age_days):
    if not cfg.get("enabled"):
        return
    since = int(time.time() - max_age_days * 86400)
    for q in cfg["queries"]:
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"points>={cfg['min_points']},created_at_i>{since}",
                    "hitsPerPage": 30,
                },
                headers=UA,
                timeout=20,
            )
            r.raise_for_status()
        except Exception as e:
            print(f"  ! HN '{q}': {e}")
            continue
        for h in r.json()["hits"]:
            if not h.get("url"):
                continue
            yield {
                "title": h["title"],
                "url": normalize(h["url"]),
                "summary": "",
                "source": "Hacker News",
                "published": h["created_at_i"],
                "points": h["points"],
            }
