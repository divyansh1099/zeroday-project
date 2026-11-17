"""Download an article, strip it to readable HTML, and fetch its images."""
import hashlib
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from readability import Document

from .sources import UA

MAX_IMG_BYTES = 3_000_000
IMG_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}


def extract(article, max_images):
    """Returns (html, word_count, images) or None. images: [(filename, mime, bytes)]."""
    try:
        r = requests.get(article["url"], headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  ! fetch failed {article['url']}: {e}")
        return None

    doc = Document(r.text)
    soup = BeautifulSoup(doc.summary(html_partial=True), "lxml")
    words = len(soup.get_text(" ").split())

    for t in soup(["script", "style", "iframe", "form", "svg", "noscript", "button"]):
        t.decompose()

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or len(images) >= max_images:
            img.decompose()
            continue
        try:
            ir = requests.get(urljoin(article["url"], src), headers=UA, timeout=20)
            mime = ir.headers.get("content-type", "").split(";")[0]
            if ir.status_code != 200 or mime not in IMG_TYPES or len(ir.content) > MAX_IMG_BYTES:
                raise ValueError("unusable image")
        except Exception:
            img.decompose()
            continue
        name = f"img_{hashlib.md5(ir.content).hexdigest()[:12]}.{IMG_TYPES[mime]}"
        images.append((name, mime, ir.content))
        img.attrs = {"src": f"images/{name}", "alt": img.get("alt", "")}

    body = soup.body.decode_contents() if soup.body else str(soup)
    return body, words, images
