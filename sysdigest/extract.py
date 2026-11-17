"""Turn an article into clean, Kindle-friendly HTML with embedded images."""
import hashlib
import io
from urllib.parse import urljoin

import cairosvg
import requests
from bs4 import BeautifulSoup
from PIL import Image
from readability import Document

from .sources import HEADERS

MAX_IMG_BYTES = 5_000_000
MAX_IMG_WIDTH = 1200  # Kindle screens are ~1000-1300px wide; keeps the EPUB small
NATIVE = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}
KEEP_ATTRS = {"href", "src", "alt", "colspan", "rowspan"}
STRIP_TAGS = ["script", "style", "iframe", "form", "svg", "noscript", "button", "video", "audio"]


def _image_src(img):
    """Best real image URL, handling lazy-loading and srcset (largest candidate)."""
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        last = srcset.split(",")[-1].strip().split(" ")[0]
        if last and not last.startswith("data:"):
            return last
    for attr in ("data-src", "data-original", "src"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return v
    return None


def _is_svg(url, content_type, content):
    return ("svg" in content_type or url.lower().split("?")[0].endswith(".svg")
            or content.lstrip()[:200].lower().startswith((b"<svg", b"<?xml")) and b"<svg" in content[:2000])


def _fetch_image(url):
    """Download an image and return (filename, mime, bytes); converts WebP/AVIF etc. to JPEG."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200 or len(r.content) > MAX_IMG_BYTES:
        return None
    content = r.content
    if _is_svg(url, r.headers.get("content-type", ""), content):
        # Many engineering blogs draw diagrams as SVG; rasterize so every Kindle shows them.
        content = cairosvg.svg2png(bytestring=content, output_width=MAX_IMG_WIDTH,
                                   background_color="white")
    im = Image.open(io.BytesIO(content))
    fmt = Image.MIME.get(im.format, "")
    if fmt in NATIVE and im.width <= MAX_IMG_WIDTH:
        data, mime = content, fmt
    else:
        if im.width > MAX_IMG_WIDTH:
            im = im.resize((MAX_IMG_WIDTH, round(im.height * MAX_IMG_WIDTH / im.width)))
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        data, mime = buf.getvalue(), "image/jpeg"
    name = f"img_{hashlib.md5(data).hexdigest()[:12]}.{NATIVE[mime]}"
    return name, mime, data


def _download_page(url):
    if url.startswith("http://"):  # prefer HTTPS; fall back to plain HTTP
        try:
            return _download_page("https://" + url[len("http://"):])
        except Exception:
            pass
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    if "html" not in r.headers.get("content-type", "text/html"):
        raise ValueError(f"not HTML ({r.headers.get('content-type')})")
    return Document(r.text).summary(html_partial=True)


def extract(article, max_images):
    """Returns (html, word_count, images) or None. images: [(filename, mime, bytes)]."""
    try:
        raw = _download_page(article["url"])
    except Exception as e:
        print(f"  ! fetch failed {article['url']}: {e}")
        return None

    soup = BeautifulSoup(raw, "lxml")
    for t in soup(STRIP_TAGS):
        t.decompose()
    words = len(soup.get_text(" ").split())

    images = []
    for img in soup.find_all("img"):
        src = _image_src(img)
        got = None
        if src and len(images) < max_images:
            try:
                got = _fetch_image(urljoin(article["url"], src))
            except Exception:
                pass
        if not got:
            img.decompose()
            continue
        images.append(got)
        img.attrs = {"src": f"images/{got[0]}", "alt": img.get("alt", "")}

    # drop <picture>/<source> wrappers whose srcsets now point nowhere
    for s in soup.find_all("source"):
        s.decompose()
    # site CSS classes / inline styles fight the Kindle's own typography
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in KEEP_ATTRS}

    body = soup.body.decode_contents() if soup.body else str(soup)
    return body, words, images
