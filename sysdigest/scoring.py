"""Heuristic quality signals: topical relevance, community votes, and article depth."""
import math
import re

# Lobsters has ~10x fewer voters than HN; scale so scores are comparable.
POINT_SCALE = {"Hacker News": 1.0, "Lobsters": 10.0}


def _hits(title, weights):
    """Keywords match at a word start: "scal" matches "scaling", "ai" won't match "main".
    End a keyword with \\b in config to require the whole word (e.g. "ai\\b")."""
    return sum(w for kw, w in weights.items() if re.search(r"\b" + kw, title))


def relevance(article, keywords, negative):
    """Keyword score on the title. 0 means off-topic, regardless of popularity."""
    title = article["title"].lower()
    pos = _hits(title, keywords)
    if pos <= 0:
        return 0.0
    return pos + _hits(title, negative)


def popularity(article):
    pts = article["points"] * POINT_SCALE.get(article["source"], 1.0)
    return 1.5 * math.log10(max(pts, 1)) + 0.5 * math.log10(1 + article["comments"])


def depth(words, n_images, html):
    """Rewards long-form, diagram-rich, technical writing."""
    score = min(words, 5000) / 1000          # up to +5 for length
    score += min(n_images, 6) * 0.4          # diagrams matter for system design
    score += min(html.count("<pre"), 5) * 0.2
    score += min(html.count("<h2") + html.count("<h3"), 8) * 0.1  # structured
    return score
