"""Rank candidates by keyword relevance plus Hacker News popularity."""
import math
import re


def score(article, keywords, negative):
    title = article["title"].lower()
    summary = re.sub(r"<[^>]+>", " ", article["summary"]).lower()
    total = 0.0
    for kw, w in {**keywords, **negative}.items():
        if kw in title:
            total += 2 * w
        elif kw in summary:
            total += w
    if article["points"]:
        total += math.log10(article["points"]) * 1.5
    return total
