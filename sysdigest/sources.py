"""Discover candidate articles from anywhere on the web.

Hacker News and Lobste.rs are the discovery engines: they link to any site, and
their votes are a quality signal. A topic can optionally add a few RSS feeds
(e.g. vendor engineering blogs that rarely trend on HN); those items carry no
votes, so they must earn their place on content alone.
"""
import calendar
import time
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

HEADERS = {
    "User-Agent": "sysdigest/2.0 (personal reading digest)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TRACKING = ("utm_", "ref", "fbclid", "gclid", "mc_cid", "mc_eid")
# Links that aren't readable articles (videos, repos, social posts).
NON_ARTICLE_HOSTS = ("youtube.com", "youtu.be", "twitter.com", "x.com", "github.com",
                     "reddit.com", "linkedin.com", "vimeo.com", "news.ycombinator.com")


def normalize(url):
    """Lowercase host, drop trailing slash and tracking params, keep meaningful query args."""
    p = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(TRACKING)])
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), query, ""))


def domain(url):
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_article(url):
    d = domain(url)
    return (url.startswith("http") and not url.lower().endswith(".pdf")
            and not any(d == h or d.endswith("." + h) for h in NON_ARTICLE_HOSTS))


def _candidate(title, url, source, published, points, comments, discussion):
    return {"title": title.strip(), "url": normalize(url), "source": source,
            "published": published, "points": points, "comments": comments,
            "discussion": discussion, "summary": "", "content": ""}


def _hn_search(query, min_points, since, hits):
    r = requests.get(
        "https://hn.algolia.com/api/v1/search",
        params={"query": query, "tags": "story", "hitsPerPage": hits,
                "numericFilters": f"points>={min_points},created_at_i>{since}"},
        headers=HEADERS, timeout=20)
    r.raise_for_status()
    for h in r.json()["hits"]:
        if h.get("url") and is_article(h["url"]):
            yield _candidate(h["title"], h["url"], "Hacker News", h["created_at_i"],
                             h["points"], h.get("num_comments") or 0,
                             f"https://news.ycombinator.com/item?id={h['objectID']}")


def from_hackernews(cfg):
    """Recent highly-voted stories, plus all-time classics with a much higher bar."""
    now = time.time()
    passes = [(cfg["recent_days"], cfg["min_points"]),
              (cfg["classics_years"] * 365, cfg["classics_min_points"])]
    for q in cfg["queries"]:
        for days, min_points in passes:
            try:
                yield from _hn_search(q, min_points, int(now - days * 86400), 50)
            except Exception as e:
                print(f"  ! HN '{q}': {e}")


def from_lobsters(cfg):
    for tag in cfg["tags"]:
        for page in range(1, cfg["pages"] + 1):
            try:
                r = requests.get(f"https://lobste.rs/t/{tag}/page/{page}.json",
                                 headers=HEADERS, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"  ! Lobsters '{tag}': {e}")
                break
            for s in r.json():
                if s["score"] >= cfg["min_score"] and s.get("url") and is_article(s["url"]):
                    yield _candidate(s["title"], s["url"], "Lobsters",
                                     datetime.fromisoformat(s["created_at"]).timestamp(),
                                     s["score"], s.get("comment_count", 0), s["short_id_url"])


def from_feeds(feeds, max_age_days):
    cutoff = time.time() - max_age_days * 86400
    for feed in feeds:
        try:
            r = requests.get(feed["url"], headers=HEADERS, timeout=20)
            r.raise_for_status()
            entries = feedparser.parse(r.content).entries
        except Exception as e:
            print(f"  ! feed {feed['name']}: {e}")
            continue
        for e in entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = calendar.timegm(ts) if ts else time.time()
            if published >= cutoff and e.get("link") and is_article(e["link"]):
                c = _candidate(e.get("title", ""), e["link"], feed["name"], published, 0, 0, e["link"])
                c["from_feed"] = True
                yield c


def discover(cfg):
    if cfg["hackernews"].get("enabled", True):
        yield from from_hackernews(cfg["hackernews"])
    if cfg["lobsters"].get("enabled", True):
        yield from from_lobsters(cfg["lobsters"])
    if cfg.get("feeds"):
        yield from from_feeds(cfg["feeds"], cfg.get("feed_max_age_days", 180))
