"""Bundle articles into one EPUB (Kindle accepts EPUB via Send to Kindle email)."""
import datetime as dt
import html
from pathlib import Path
from urllib.parse import urlsplit

from ebooklib import epub

CSS = """
body { line-height: 1.5; }
h1 { font-size: 1.5em; margin-bottom: 0.2em; }
.meta { color: #555; font-size: 0.85em; margin-bottom: 0.8em; }
.why { font-style: italic; margin-bottom: 1.5em; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
pre, code { font-family: monospace; font-size: 0.85em; white-space: pre-wrap; }
blockquote { margin-left: 1em; padding-left: 0.8em; border-left: 3px solid #999; }
table { border-collapse: collapse; font-size: 0.85em; }
td, th { border: 1px solid #999; padding: 0.2em 0.4em; }
"""


def build_epub(articles, path):
    today = dt.date.today().isoformat()
    book = epub.EpubBook()
    book.set_identifier(f"sysdigest-{today}")
    book.set_title(f"System Design Digest {today}")
    book.set_language("en")
    book.add_author("sysdigest")

    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(style)

    chapters, seen_imgs = [], set()
    for i, a in enumerate(articles, 1):
        for name, mime, data in a["images"]:
            if name not in seen_imgs:
                seen_imgs.add(name)
                book.add_item(epub.EpubItem(
                    uid=name, file_name=f"images/{name}", media_type=mime, content=data))
        published = dt.date.fromtimestamp(a["published"]).isoformat()
        ch = epub.EpubHtml(title=a["title"], file_name=f"a{i}.xhtml", lang="en")
        ch.add_item(style)
        site = urlsplit(a["url"]).netloc.removeprefix("www.")
        why = f"<p class=\"why\">{html.escape(a['why'])}</p>" if a.get("why") else ""
        ch.content = (
            f"<h1>{html.escape(a['title'])}</h1>"
            f"<p class=\"meta\">{html.escape(site)} &middot; {published} &middot; "
            f"~{max(1, a['words'] // 230)} min read &middot; "
            f"<a href=\"{html.escape(a['url'])}\">original</a> &middot; "
            f"<a href=\"{html.escape(a['discussion'])}\">{a['points']} pts on "
            f"{html.escape(a['source'])}</a></p>{why}{a['html']}"
        )
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return Path(path)
