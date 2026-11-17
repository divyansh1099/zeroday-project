"""Email the EPUB to your Kindle address over SMTP. Credentials come from env vars."""
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

REQUIRED = ["KINDLE_EMAIL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"]


def send_to_kindle(path):
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)} (see README)")

    sender = os.environ.get("FROM_EMAIL", os.environ["SMTP_USER"])
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, os.environ["KINDLE_EMAIL"], "System Design Digest"
    msg.set_content("Your system design reading digest.")
    p = Path(path)
    msg.add_attachment(p.read_bytes(), maintype="application", subtype="epub+zip", filename=p.name)

    port = int(os.environ.get("SMTP_PORT", 587))
    host = os.environ["SMTP_HOST"]
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=60)
    else:
        server = smtplib.SMTP(host, port, timeout=60)
        server.starttls()
    with server:
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)
