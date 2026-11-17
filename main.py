#!/usr/bin/env python3
"""Find the best system design reads on the web and send them to your Kindle.

Two ways to run it:

  Editor mode (best quality): a person or an AI agent reads the candidates and picks.
    python main.py gather                 # discover + download; writes out/candidates/
    # read out/candidates/*.md, write picks.yaml (see README)
    python main.py build picks.yaml       # build the EPUB from the picks
    python main.py build picks.yaml --send   # ...and email it to your Kindle

  Automatic mode (the built-in editor reads every article's full text and judges it):
    python main.py auto [--send]

Only articles that clear the bar are sent; the digest is never padded to hit a number.
"""
import argparse
import datetime as dt
import pickle
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from sysdigest import editor, scoring, sources
from sysdigest.epub import build_epub
from sysdigest.extract import extract
from sysdigest.mailer import send_to_kindle
from sysdigest.store import Store

OUT = Path("out")
POOL = OUT / "pool.pkl"
CANDIDATES = OUT / "candidates"


def discover(cfg, store):
    """Unseen, on-topic candidates, merged across aggregators, best-first."""
    cands = {}
    for a in sources.discover(cfg):
        if store.seen(a["url"]):
            continue
        prev = cands.get(a["url"])
        if prev is None or scoring.popularity(a) > scoring.popularity(prev):
            cands[a["url"]] = a
    for a in cands.values():
        a["relevance"] = scoring.relevance(a, cfg["keywords"], cfg.get("negative_keywords", {}))
        a["prelim"] = a["relevance"] + scoring.popularity(a)
    # Feed items skip the title gate: few, unvoted, judged on full text by the editor.
    on_topic = [a for a in cands.values() if a["relevance"] > 0 or a.get("from_feed")]
    print(f"{len(cands)} unseen candidates, {len(on_topic)} on-topic")
    return sorted(on_topic, key=lambda a: a["prelim"], reverse=True)


def fetch(article, cfg):
    try:
        res = extract(article, cfg["max_images_per_article"])
    except Exception as e:  # one weird page must not kill the whole digest
        print(f"  ! extract failed {article['url']}: {e}")
        return None
    if not res or res[1] < cfg["min_words"]:
        return None
    article["html"], article["words"], article["images"] = res
    article["depth"] = scoring.depth(article["words"], len(article["images"]), article["html"])
    article["heuristic"] = article["prelim"] + article["depth"]
    article["editor"], article["reject"], _ = editor.judge(article["title"], article["html"], cfg["topic_re"])
    return article


def gather_pool(cfg):
    ranked = discover(cfg, Store())
    with ThreadPoolExecutor(max_workers=8) as ex:
        todo = ranked[:cfg["candidate_pool"]]
        todo += [a for a in ranked[cfg["candidate_pool"]:] if a.get("from_feed")]  # always read feeds
        fetched = list(ex.map(lambda a: fetch(a, cfg), todo))
    pool = [a for a in fetched if a]
    print(f"{len(pool)} long-form articles fetched")
    return sorted(pool, key=lambda a: (a["editor"], a["heuristic"]), reverse=True)


def write_candidates(pool):
    """Save each candidate as readable text so an editor can judge it."""
    OUT.mkdir(exist_ok=True)
    CANDIDATES.mkdir(exist_ok=True)
    for f in CANDIDATES.glob("*.md"):
        f.unlink()
    POOL.write_bytes(pickle.dumps(pool))
    index = ["# Candidates (built-in editor's score first)\n",
             "| # | editor | words | imgs | votes | title | verdict / url |",
             "|---|---|---|---|---|---|---|"]
    for i, a in enumerate(pool, 1):
        slug = re.sub(r"[^a-z0-9]+", "-", a["title"].lower()).strip("-")[:50]
        text = BeautifulSoup(a["html"], "lxml").get_text("\n")
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        (CANDIDATES / f"{i:02d}-{slug}.md").write_text(
            f"# {a['title']}\n\nURL: {a['url']}\nVotes: {a['points']} on {a['source']} "
            f"({a['comments']} comments)\nWords: {a['words']}  Images: {len(a['images'])}  "
            f"Editor score: {a['editor']:.1f}/10 {a['reject']}\n\n---\n\n{text}\n")
        index.append(f"| {i} | {a['editor']:.1f} | {a['words']} | {len(a['images'])} | "
                     f"{a['points']} {a['source']} | {a['title']} | {a['reject'] or a['url']} |")
    (CANDIDATES / "INDEX.md").write_text("\n".join(index) + "\n")
    print(f"Wrote {len(pool)} candidates to {CANDIDATES}/ (see INDEX.md)")


def auto_picks(pool, cfg, limit, verbose=True):
    """Automatic mode: the built-in editor judges each article; the best few are kept.

    Rules: score >= min_editor_score, at most one article per site, at most
    max_postmortems outage write-ups so the digest stays varied. Never padded.
    """
    for a in pool:
        a["editor"], a["reject"], _ = editor.judge(a["title"], a["html"], cfg["topic_re"])
        # editor judgment dominates; community votes and depth only break ties
        a["final"] = a["editor"] + (a["prelim"] + a["depth"]) / 100
    picked, sites, postmortems = [], set(), 0
    for a in sorted(pool, key=lambda a: a["final"], reverse=True):
        d = sources.domain(a["url"])
        is_pm = bool(editor.POSTMORTEM.search(a["title"]))
        ok = (a["editor"] >= cfg["min_editor_score"] and d not in sites and len(picked) < limit
              and not (is_pm and postmortems >= cfg["max_postmortems"]))
        if ok:
            a["why"] = editor.why_line(a["html"], topic_re=cfg["topic_re"])
            picked.append(a)
            sites.add(d)
            postmortems += is_pm
        if verbose:
            note = a["reject"] or ("" if ok else "passed, but over a variety limit or below the bar")
            print(f"  {'+' if ok else '-'} [{a['editor']:4.1f}] {a['title'][:60]}  {note}")
    return picked


def editor_picks(picks_file, pool):
    """Editor mode: picks.yaml is a list of {url, why}, in reading order."""
    by_url = {a["url"]: a for a in pool}
    picked = []
    for p in yaml.safe_load(Path(picks_file).read_text()) or []:
        a = by_url.get(sources.normalize(p["url"]))
        if not a:
            sys.exit(f"Not in the gathered pool (run `gather` first): {p['url']}")
        a["why"] = p.get("why", "")
        picked.append(a)
    return picked


def deliver(picked, send, digest_title):
    if not picked:
        print("Nothing cleared the quality bar this time; not sending anything.")
        return None
    OUT.mkdir(exist_ok=True)
    # Number same-day digests (#2, #3...) so files and Kindle titles never collide.
    base, n = f"{digest_title} {dt.date.today()}", 1
    while (OUT / f"{base}{f' #{n}' if n > 1 else ''}.epub").exists():
        n += 1
    title = f"{base}{f' #{n}' if n > 1 else ''}"
    path = build_epub(picked, OUT / f"{title}.epub", title=title)
    print(f"\nBuilt {path} ({path.stat().st_size // 1024} KB) with {len(picked)} articles:")
    for a in picked:
        print(f"  * {a['title']} ({sources.domain(a['url'])})")
    if send:
        send_to_kindle(path)
        print("Emailed to your Kindle.")
    return path


def load_config(path, topic=None):
    """Shared settings merged with one topic profile (topic keys win)."""
    raw = yaml.safe_load(Path(path).read_text())
    topics = raw.pop("topics")
    name = topic or raw.pop("default_topic")
    raw.pop("default_topic", None)
    if name not in topics:
        sys.exit(f"Unknown topic {name!r}; choose from: {', '.join(topics)}")
    cfg = {**raw, **topics[name], "topic": name}
    terms = cfg.get("editor_terms")
    cfg["topic_re"] = editor.terms_regex(terms) if terms else editor.TOPIC_TERMS
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-t", "--topic", help="topic profile from config.yaml (default: default_topic)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gather", help="discover and download candidates for an editor to review")
    b = sub.add_parser("build", help="build the EPUB from an editor's picks.yaml")
    b.add_argument("picks")
    b.add_argument("--send", action="store_true", help="email the EPUB to your Kindle")
    b.add_argument("--mark", action="store_true",
                   help="record the picks as sent without emailing (delivered another way)")
    a = sub.add_parser("auto", help="pick automatically with the built-in editor")
    a.add_argument("--send", action="store_true", help="email the EPUB to your Kindle")
    a.add_argument("-n", type=int, help="override max_articles")
    args = ap.parse_args()

    cfg = load_config(args.config, args.topic)
    print(f"Topic: {cfg['topic']}")

    if args.cmd == "gather":
        write_candidates(gather_pool(cfg))
    elif args.cmd == "build":
        picked = editor_picks(args.picks, pickle.loads(POOL.read_bytes()))
        if deliver(picked, args.send, cfg["title"]) and (args.send or args.mark):
            Store().mark(picked)
    else:
        picked = auto_picks(gather_pool(cfg), cfg, args.n or cfg["max_articles"])
        if deliver(picked, args.send, cfg["title"]) and args.send:
            Store().mark(picked)


if __name__ == "__main__":
    main()
