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
from sysdigest import epub, extract, judge, mailer, scoring, sources
from sysdigest.store import Store

CFG = yaml.safe_load(open("config.yaml"))


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
def pooled(title, prelim, depth, domain="ex.com"):
    a = article(title)
    a.update(url=f"https://{domain}/{title}", prelim=prelim, depth=depth, html="<p>x</p>")
    return a


def test_select_heuristic_bar_and_one_per_site():
    pool = [pooled("great", 10, 5, "a.com"), pooled("also-great-same-site", 10, 4, "a.com"),
            pooled("weak", 3, 1, "b.com"), pooled("good", 9, 5, "c.com")]
    with mock.patch.object(judge, "available", return_value=False):
        picked = main.select(pool, CFG, limit=5)
    assert [a["title"] for a in picked] == ["great", "good"]  # never padded with "weak"


def test_select_with_claude_verdicts():
    pool = [pooled("deep", 1, 1, "a.com"), pooled("fluff", 50, 9, "b.com")]
    verdicts = {"deep": judge.Verdict(is_system_design=True, score=9, why="Great trade-offs."),
                "fluff": judge.Verdict(is_system_design=False, score=9, why="Marketing.")}
    fake = mock.Mock(grade=lambda a: verdicts[a["title"]])
    with mock.patch.object(judge, "available", return_value=True), \
         mock.patch.object(judge, "Judge", return_value=fake):
        picked = main.select(pool, CFG, limit=5)
    assert [a["title"] for a in picked] == ["deep"]
    assert picked[0]["why"] == "Great trade-offs."


# --- output ------------------------------------------------------------------
def test_epub_and_mail(tmp_path, monkeypatch):
    a = pooled("t", 1, 1)
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
    s = Store(tmp_path / "s.db")
    s.mark([article()])
    assert s.seen("https://ex.com/post") and not s.seen("https://ex.com/other")
