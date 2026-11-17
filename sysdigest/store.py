"""Record of articles already sent (a JSON file, tracked in git so it survives anywhere)."""
import json
import time
from pathlib import Path


class Store:
    def __init__(self, path="sent.json"):
        self.path = Path(path)
        self.sent = json.loads(self.path.read_text()) if self.path.exists() else {}

    def seen(self, url):
        return url in self.sent

    def mark(self, articles):
        for a in articles:
            self.sent[a["url"]] = {"title": a["title"], "sent_at": time.strftime("%Y-%m-%d")}
        self.path.write_text(json.dumps(self.sent, indent=1, sort_keys=True) + "\n")
