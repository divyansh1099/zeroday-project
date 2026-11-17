"""SQLite record of articles already sent, so you never get repeats."""
import sqlite3
import time


class Store:
    def __init__(self, path="sent.db"):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sent (url TEXT PRIMARY KEY, title TEXT, sent_at REAL)"
        )

    def seen(self, url):
        return self.db.execute("SELECT 1 FROM sent WHERE url=?", (url,)).fetchone() is not None

    def mark(self, articles):
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO sent VALUES (?,?,?)",
                [(a["url"], a["title"], time.time()) for a in articles],
            )
