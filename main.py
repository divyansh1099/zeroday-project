#!/usr/bin/env python3
"""Find the best system design reads on the web and send them to your Kindle.

Only articles that clear a high quality bar are sent. If nothing qualifies,
nothing is sent; the digest is never padded to hit a number.
"""
import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from sysdigest import judge, scoring, sources
from sysdigest.epub import build_epub
from sysdigest.extract import extract
from sysdigest.mailer import send_to_kindle
from sysdigest.store import Store


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
    return article


def select(pool, cfg, limit):
    """Apply the quality bar and keep at most one article per site."""
    q = cfg["quality"]
    editor = None
    if q.get("use_claude", True) and judge.available():
        editor = judge.Judge(q["claude_model"])
        print(f"Grading {len(pool)} articles with Claude ({q['claude_model']})...")
    else:
        print("Claude editor off (no Anthropic credentials): using heuristics only.")

    for a in pool:
        a["verdict"] = editor.grade(a) if editor else None
        v = a["verdict"]
        if v:
            a["passed"] = v.is_system_design and v.score >= q["min_claude_score"]
            a["final"] = v.score + a["prelim"] / 100  # votes only break ties
            a["why"] = v.why
        else:
            a["final"] = a["prelim"] + a["depth"]
            a["passed"] = a["final"] >= q["min_heuristic_score"]
            a["why"] = ""
        mark = "+" if a["passed"] else "-"
        grade = f"claude {v.score}/10" if v else f"heuristic {a['final']:.1f}"
        print(f"  {mark} [{grade}] {a['title']} ({sources.domain(a['url'])})")

    picked, sites = [], set()
    for a in sorted((a for a in pool if a["passed"]), key=lambda a: a["final"], reverse=True):
        d = sources.domain(a["url"])
        if d not in sites and len(picked) < limit:
            picked.append(a)
            sites.add(d)
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the EPUB locally; don't email or mark as sent")
    ap.add_argument("-n", type=int, help="override max_articles")
    ap.add_argument("--out", default="out", help="directory for EPUB output")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    limit = args.n or cfg["max_articles"]
    store = Store()

    print("Discovering articles...")
    ranked = discover(cfg, store)

    # Download the most promising candidates in parallel.
    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = list(ex.map(lambda a: fetch(a, cfg), ranked[:cfg["candidate_pool"]]))
    pool = [a for a in fetched if a]
    print(f"{len(pool)} long-form articles fetched")

    picked = select(pool, cfg, limit)
    if not picked:
        print("Nothing cleared the quality bar this time; not sending anything.")
        return

    Path(args.out).mkdir(exist_ok=True)
    path = build_epub(picked, Path(args.out) / f"system-design-digest-{dt.date.today()}.epub")
    print(f"\nBuilt {path} ({path.stat().st_size // 1024} KB) with {len(picked)} articles:")
    for a in picked:
        print(f"  * {a['title']} ({sources.domain(a['url'])})")

    if args.dry_run:
        print("Dry run: not sending.")
        return
    send_to_kindle(path)
    store.mark(picked)
    print(f"Sent {len(picked)} articles to your Kindle.")


if __name__ == "__main__":
    main()
