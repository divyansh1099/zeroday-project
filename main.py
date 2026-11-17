#!/usr/bin/env python3
"""Find great system design reads and send them to your Kindle."""
import argparse
from pathlib import Path

import yaml

from sysdigest import scoring, sources
from sysdigest.epub import build_epub
from sysdigest.extract import extract
from sysdigest.mailer import send_to_kindle
from sysdigest.store import Store


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

    print("Collecting candidates...")
    cands = {}
    for a in [*sources.from_feeds(cfg["feeds"], cfg["max_age_days"]),
              *sources.from_hackernews(cfg.get("hackernews", {}), cfg["max_age_days"])]:
        if not store.seen(a["url"]):
            # keep the version with more signal if duplicated across sources
            if a["url"] not in cands or a["points"] > cands[a["url"]]["points"]:
                cands[a["url"]] = a

    for a in cands.values():
        a["score"] = scoring.score(a, cfg["keywords"], cfg.get("negative_keywords", {}))
    ranked = sorted((a for a in cands.values() if a["score"] >= cfg["min_score"]),
                    key=lambda a: a["score"], reverse=True)
    print(f"{len(cands)} unseen candidates, {len(ranked)} above min_score")

    picked = []
    for a in ranked:
        if len(picked) >= limit:
            break
        res = extract(a, cfg["max_images_per_article"])
        if not res:
            continue
        body, words, images = res
        if words < cfg["min_words"]:
            continue
        a.update(html=body, images=images, words=words)
        picked.append(a)
        print(f"  + [{a['score']:.1f}] {a['title']} ({a['source']}, {words} words)")

    if not picked:
        print("Nothing new worth sending.")
        return

    Path(args.out).mkdir(exist_ok=True)
    path = build_epub(picked, Path(args.out) / "system-design-digest.epub")
    print(f"Built {path}")

    if args.dry_run:
        print("Dry run: not sending.")
        return
    send_to_kindle(path)
    store.mark(picked)
    print(f"Sent {len(picked)} articles to your Kindle.")


if __name__ == "__main__":
    main()
