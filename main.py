#!/usr/bin/env python3
"""Find the best system design reads on the web and send them to your Kindle.

Two ways to run it:

  Editor mode (best quality): a person or an AI agent reads the candidates and picks.
    python main.py gather                 # discover + download; writes out/candidates/
    # read out/candidates/*.md, write picks.yaml (see README)
    python main.py build picks.yaml       # build the EPUB from the picks
    python main.py build picks.yaml --send   # ...and email it to your Kindle

  Automatic mode (no editor, heuristic quality bar):
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

from sysdigest import scoring, sources
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
    on_topic = [a for a in cands.values() if a["relevance"] > 0]
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
    return article


def gather_pool(cfg):
    ranked = discover(cfg, Store())
    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = list(ex.map(lambda a: fetch(a, cfg), ranked[:cfg["candidate_pool"]]))
    pool = [a for a in fetched if a]
    print(f"{len(pool)} long-form articles fetched")
    return sorted(pool, key=lambda a: a["heuristic"], reverse=True)


def write_candidates(pool):
    """Save each candidate as readable text so an editor can judge it."""
    OUT.mkdir(exist_ok=True)
    CANDIDATES.mkdir(exist_ok=True)
    for f in CANDIDATES.glob("*.md"):
        f.unlink()
    POOL.write_bytes(pickle.dumps(pool))
    index = ["# Candidates (best heuristic score first)\n",
             "| # | heuristic | words | imgs | votes | title | url |", "|---|---|---|---|---|---|---|"]
    for i, a in enumerate(pool, 1):
        slug = re.sub(r"[^a-z0-9]+", "-", a["title"].lower()).strip("-")[:50]
        text = BeautifulSoup(a["html"], "lxml").get_text("\n")
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        (CANDIDATES / f"{i:02d}-{slug}.md").write_text(
            f"# {a['title']}\n\nURL: {a['url']}\nVotes: {a['points']} on {a['source']} "
            f"({a['comments']} comments)\nWords: {a['words']}  Images: {len(a['images'])}  "
            f"Heuristic score: {a['heuristic']:.1f}\n\n---\n\n{text}\n")
        index.append(f"| {i} | {a['heuristic']:.1f} | {a['words']} | {len(a['images'])} | "
                     f"{a['points']} {a['source']} | {a['title']} | {a['url']} |")
    (CANDIDATES / "INDEX.md").write_text("\n".join(index) + "\n")
    print(f"Wrote {len(pool)} candidates to {CANDIDATES}/ (see INDEX.md)")


def heuristic_picks(pool, cfg, limit):
    """Automatic mode: heuristic bar, at most one article per site."""
    picked, sites = [], set()
    for a in pool:  # already sorted best-first
        d = sources.domain(a["url"])
        if a["heuristic"] >= cfg["min_heuristic_score"] and d not in sites and len(picked) < limit:
            a["why"] = ""
            picked.append(a)
            sites.add(d)
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


def deliver(picked, send):
    if not picked:
        print("Nothing cleared the quality bar this time; not sending anything.")
        return None
    OUT.mkdir(exist_ok=True)
    path = build_epub(picked, OUT / f"system-design-digest-{dt.date.today()}.epub")
    print(f"\nBuilt {path} ({path.stat().st_size // 1024} KB) with {len(picked)} articles:")
    for a in picked:
        print(f"  * {a['title']} ({sources.domain(a['url'])})")
    if send:
        send_to_kindle(path)
        print("Emailed to your Kindle.")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gather", help="discover and download candidates for an editor to review")
    b = sub.add_parser("build", help="build the EPUB from an editor's picks.yaml")
    b.add_argument("picks")
    b.add_argument("--send", action="store_true", help="email the EPUB to your Kindle")
    b.add_argument("--mark", action="store_true",
                   help="record the picks as sent without emailing (delivered another way)")
    a = sub.add_parser("auto", help="pick with heuristics only, no editor")
    a.add_argument("--send", action="store_true", help="email the EPUB to your Kindle")
    a.add_argument("-n", type=int, help="override max_articles")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())

    if args.cmd == "gather":
        write_candidates(gather_pool(cfg))
    elif args.cmd == "build":
        picked = editor_picks(args.picks, pickle.loads(POOL.read_bytes()))
        if deliver(picked, args.send) and (args.send or args.mark):
            Store().mark(picked)
    else:
        picked = heuristic_picks(gather_pool(cfg), cfg, args.n or cfg["max_articles"])
        if deliver(picked, args.send) and args.send:
            Store().mark(picked)


if __name__ == "__main__":
    main()
