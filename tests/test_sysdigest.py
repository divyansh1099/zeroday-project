"""Offline tests: no network, no SMTP server, no API key needed."""
import io
import smtplib
import zipfile
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml
from PIL import Image

import main
from sysdigest import editor, epub, extract, mailer, scoring, sources
from sysdigest.store import Store

CFG = main.load_config("config.yaml", "system-design")
AI = main.load_config("config.yaml", "ai-engineering")


def article(title="How we sharded our database at scale", points=300, source="Hacker News"):
    return sources._candidate(title, "https://ex.com/post", source, 1.7e9, points, 50,
                              "https://news.ycombinator.com/item?id=1")


def image_bytes(fmt, width=50):
    buf = io.BytesIO()
    Image.new("RGBA" if fmt == "WEBP" else "RGB", (width, 20), "red").save(buf, fmt)
    return buf.getvalue()


# --- sources -----------------------------------------------------------------
def test_normalize_strips_tracking_but_keeps_real_query():
    assert sources.normalize("https://EX.com/a/?utm_source=x&id=42") == "https://ex.com/a?id=42"
    assert sources.normalize("https://ex.com/p?id=1") != sources.normalize("https://ex.com/p?id=2")


@pytest.mark.parametrize("url,ok", [
    ("https://blog.example.com/post", True),
    ("https://www.youtube.com/watch?v=1", False),
    ("https://github.com/foo/bar", False),
    ("https://example.com/paper.pdf", False),
])
def test_is_article(url, ok):
    assert sources.is_article(url) is ok


# --- scoring -----------------------------------------------------------------
def test_popular_but_off_topic_scores_zero():
    a = article("Show HN: My cat photo app", points=5000)
    assert scoring.relevance(a, CFG["keywords"], CFG["negative_keywords"]) == 0


def test_lobsters_points_are_scaled_like_hn():
    hn = scoring.popularity(article(points=300))
    lob = scoring.popularity(article(points=30, source="Lobsters"))
    assert abs(hn - lob) < 0.01


def test_depth_rewards_diagrams_and_length():
    assert scoring.depth(4000, 5, "<h2>x</h2>") > scoring.depth(1200, 0, "")


# --- extract -----------------------------------------------------------------
def fake_get(page_html, images):
    def get(url, **kw):
        if url in images:
            return SimpleNamespace(status_code=200, content=images[url], headers={})
        return SimpleNamespace(status_code=200, text=page_html, raise_for_status=lambda: None,
                               headers={"content-type": "text/html; charset=utf-8"})
    return get


def test_extract_handles_lazy_images_webp_and_strips_junk():
    page = ("<html><body><article><h1>T</h1><p class='x' style='color:red'>" + "word " * 1500 +
            "</p><img src='data:image/gif;base64,xx' data-src='/lazy.webp'>"
            "<img srcset='/small.png 400w, /big.png 1600w'><script>evil()</script>"
            "</article></body></html>")
    imgs = {"https://ex.com/lazy.webp": image_bytes("WEBP"),
            "https://ex.com/big.png": image_bytes("PNG", width=1600)}
    with mock.patch("requests.get", fake_get(page, imgs)):
        html, words, images = extract.extract(article(), max_images=5)
    assert words >= 1500
    assert [m for _, m, _ in images] == ["image/jpeg", "image/jpeg"]  # webp + oversized converted
    assert Image.open(io.BytesIO(images[1][2])).width == extract.MAX_IMG_WIDTH
    assert "evil" not in html and "style=" not in html and "class=" not in html


def test_extract_rejects_non_html():
    resp = SimpleNamespace(status_code=200, text="%PDF", raise_for_status=lambda: None,
                           headers={"content-type": "application/pdf"})
    with mock.patch("requests.get", return_value=resp):
        assert extract.extract(article(), 5) is None


# --- selection ---------------------------------------------------------------
SYSTEMS_TEXT = (
    "<h2>Design</h2><p>We migrated the database to a sharded cluster because a single leader "
    "became the bottleneck at 40,000 writes per second. Instead of global consensus, each shard "
    "replicates to three nodes, so read latency dropped from 120 ms to 9 ms. The trade-off is "
    "cross-shard transactions, which we measured at 2% of traffic. As a result, cache hit rate "
    "rose to 97% and we deployed the new storage layer across every region.</p>") * 30

SHIP_TEXT = ("<p>The hull of a ship displaces water, and buoyancy keeps it afloat. Naval "
             "architecture studies stability, the keel, ballast and how waves push the bow.</p>") * 40

SECURITY_TEXT = SYSTEMS_TEXT[:2000] + ("<p>The attackers published a malicious payload that "
    "exploited a vulnerability and compromised maintainers; the malware stole tokens.</p>") * 40

SALES_TEXT = SYSTEMS_TEXT[:3000] + "<p>Book a demo. Sign up for a free trial. Get started today. Contact sales.</p>"


@pytest.mark.parametrize("html,reason", [
    (SHIP_TEXT, "off-topic"), (SECURITY_TEXT, "security"), (SALES_TEXT, "marketing"),
])
def test_editor_rejects_with_reason(html, reason):
    score, why_not, _ = editor.judge("Some title", html)
    assert score == 0 and reason in why_not


def test_editor_rewards_substantive_systems_writing():
    score, why_not, f = editor.judge("How we sharded our database", SYSTEMS_TEXT)
    assert why_not == "" and score >= 8.5 and f["quant"] > 5


def test_why_line_prefers_facts_over_boilerplate():
    html = ("<p>We sincerely apologize to our customers and are offering service credits to everyone affected.</p>"
            "<p>Read latency dropped from 120 ms to 9 ms once each shard replicated to three nodes.</p>")
    assert editor.why_line(html).startswith("Read latency dropped")


def pooled(title, html=SYSTEMS_TEXT, domain="ex.com"):
    a = article(title)
    a.update(url=f"https://{domain}/{title.replace(' ', '-')}", html=html, prelim=5, depth=3, heuristic=8)
    return a


def test_auto_picks_bar_variety_and_no_padding():
    pool = [pooled("Outage postmortem one", domain="a.com"), pooled("Outage postmortem two", domain="b.com"),
            pooled("Outage postmortem three", domain="c.com"), pooled("Sharding deep dive", domain="a.com"),
            pooled("Ship hulls", SHIP_TEXT, "d.com"), pooled("Caching at scale", domain="e.com")]
    picked = main.auto_picks(pool, CFG, limit=10, verbose=False)
    titles = [a["title"] for a in picked]
    assert "Ship hulls" not in titles                                  # never padded with junk
    assert sum("postmortem" in t for t in titles) == CFG["max_postmortems"]
    assert len({sources.domain(a["url"]) for a in picked}) == len(picked)  # one per site
    assert all(a["why"] for a in picked)


def test_editor_picks_keep_order_and_why(tmp_path):
    pool = [pooled("one"), pooled("two")]
    picks = tmp_path / "picks.yaml"
    picks.write_text("- url: https://ex.com/two/?utm_source=x\n  why: Read me first.\n"
                     "- url: https://ex.com/one\n")
    picked = main.editor_picks(picks, pool)
    assert [a["title"] for a in picked] == ["two", "one"]
    assert picked[0]["why"] == "Read me first." and picked[1]["why"] == ""


def test_editor_picks_reject_unknown_url(tmp_path):
    picks = tmp_path / "picks.yaml"
    picks.write_text("- url: https://nowhere.com/x\n")
    with pytest.raises(SystemExit):
        main.editor_picks(picks, [pooled("one")])


# --- output ------------------------------------------------------------------
def test_epub_and_mail(tmp_path, monkeypatch):
    a = pooled("t")
    a.update(words=2000, why="Worth it.", images=[("img_1.png", "image/png", image_bytes("PNG"))],
             html='<p>hello</p><img src="images/img_1.png"/>')
    path = epub.build_epub([a], tmp_path / "d.epub")
    names = zipfile.ZipFile(path).namelist()
    assert "EPUB/images/img_1.png" in names and "EPUB/a1.xhtml" in names

    for k, v in dict(KINDLE_EMAIL="me@kindle.com", SMTP_HOST="h", SMTP_PORT="587",
                     SMTP_USER="u@x.com", SMTP_PASSWORD="p").items():
        monkeypatch.setenv(k, v)
    with mock.patch.object(smtplib, "SMTP") as smtp:
        mailer.send_to_kindle(path)
    sent = smtp.return_value.send_message.call_args[0][0]
    assert sent["To"] == "me@kindle.com"
    assert sent.get_payload()[1].get_filename() == "d.epub"


def test_store_dedupes(tmp_path):
    path = tmp_path / "sent.json"
    Store(path).mark([article()])
    s = Store(path)  # reloads from disk
    assert s.seen("https://ex.com/post") and not s.seen("https://ex.com/other")


def test_editor_accepts_substantive_build_story_with_mixed_topics():
    """Moderate systems vocabulary is fine when dense with first-hand numbers (r/Place-style)."""
    frontend = ("<p>The canvas UI renders tiles with colors chosen by each person, and the mobile "
                "app shows the same picture on phones and tablets for everyone taking part.</p>")
    backend = ("<p>We measured 333,000 tile placements and found the backend handled 50,000 requests "
               "per second with a cache in front of the database.</p>")
    score, why_not, f = editor.judge("How we built it", (frontend * 6 + backend) * 25)
    assert 20 <= f["topic"] < 30 and why_not == "" and score > 0


def test_svg_diagrams_are_rasterized():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="blue"/></svg>'
    resp = SimpleNamespace(status_code=200, content=svg, headers={"content-type": "image/svg+xml"})
    with mock.patch("requests.get", return_value=resp):
        name, mime, data = extract._fetch_image("https://ex.com/diagram.svg")
    assert mime in ("image/png", "image/jpeg") and Image.open(io.BytesIO(data)).width == extract.MAX_IMG_WIDTH


def test_why_line_skips_heading_residue():
    html = ("<p>Mgmtd Requests Nodes don't need to maintain connections with every other node.</p>"
            "<p>Each storage node splits files into chunks and replicates them across three servers for durability.</p>")
    assert editor.why_line(html).startswith("Each storage node")


def test_editor_understands_distributed_data_vocabulary():
    """CRDT / consensus theory articles use 'merge', 'concurrent', 'converge' more than 'server'."""
    crdt = ("<p>Two replicas accept concurrent writes during a partition. Because the merge is "
            "commutative, both converge to the same state without coordination, and causal "
            "ordering with vector clocks resolves conflicts. An OR-Set keeps tombstones so "
            "eventually every replica agrees.</p>") * 30
    score, why_not, _ = editor.judge("A field guide to CRDTs", crdt)
    assert why_not == "" and score > 0


def test_title_keywords_match_whole_words():
    assert scoring.relevance(article("The main reason I said no"), AI["keywords"], AI["negative_keywords"]) == 0
    assert scoring.relevance(article("What we learned running AI agents in production"),
                             AI["keywords"], AI["negative_keywords"]) > 5


def test_ai_profile_penalizes_launches_and_news():
    kw, neg = AI["keywords"], AI["negative_keywords"]
    lessons = scoring.relevance(article("Lessons from building RAG in production"), kw, neg)
    launch = scoring.relevance(article("Launch HN: Acme (YC W26) – RAG for everyone"), kw, neg)
    assert launch < lessons / 2


def test_ai_profile_editor_vocabulary():
    body = ("<p>We built a RAG pipeline: documents are chunked, embedded and indexed in a vector "
            "store, then a reranker picks context for the LLM. Our evals measured accuracy rising "
            "from 61% to 84% while p95 latency stayed under 900 ms.</p>") * 30
    assert editor.judge("RAG lessons", body, AI["topic_re"])[1] == ""
    assert editor.judge("RAG lessons", SHIP_TEXT, AI["topic_re"])[0] == 0


def test_feed_items_are_unvoted_and_flagged():
    rss = (b'<rss version="2.0"><channel><item><title>Clean data was never enough</title>'
           b'<link>https://www.databricks.com/blog/clean-data</link>'
           b'<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>')
    resp = SimpleNamespace(content=rss, raise_for_status=lambda: None)
    with mock.patch("requests.get", return_value=resp):
        items = list(sources.from_feeds([{"name": "Databricks Blog", "url": "https://x/feed"}], 3650))
    assert len(items) == 1 and items[0]["from_feed"] and items[0]["points"] == 0
    assert items[0]["source"] == "Databricks Blog"


def test_editor_rejects_vendor_press_releases():
    pr = ("<p>We are proud to be named a Leader in the 2026 Gartner Magic Quadrant for data lakehouse "
          "platforms. Our LLM agents, RAG pipelines, Spark and Delta tables scale to production.</p>") * 20
    assert editor.judge("We're a Leader", pr, AI["topic_re"])[1] == "vendor press release"
