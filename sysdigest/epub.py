"""Bundle articles into one EPUB (Kindle accepts EPUB via Send to Kindle email)."""
import datetime as dt
import html

from ebooklib import epub


def build_epub(articles, path):
    today = dt.date.today().isoformat()
    book = epub.EpubBook()
    book.set_identifier(f"sysdigest-{today}")
    book.set_title(f"System Design Digest {today}")
    book.set_language("en")
    book.add_author("sysdigest")

    chapters, seen_imgs = [], set()
    for i, a in enumerate(articles, 1):
        for name, mime, data in a["images"]:
            if name not in seen_imgs:
                seen_imgs.add(name)
                book.add_item(epub.EpubItem(
                    uid=name, file_name=f"images/{name}", media_type=mime, content=data))
        ch = epub.EpubHtml(title=a["title"], file_name=f"a{i}.xhtml", lang="en")
        ch.content = (
            f"<h1>{html.escape(a['title'])}</h1>"
            f"<p><em>{html.escape(a['source'])} &middot; "
            f"<a href=\"{html.escape(a['url'])}\">original</a></em></p>{a['html']}"
        )
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(path, book)
    return path
