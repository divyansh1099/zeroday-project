# sysdigest

Finds great system design articles and emails them to your Kindle as one EPUB.

**How it works**
1. Pulls candidates from engineering-blog RSS feeds (`config.yaml`) and high-scoring Hacker News stories.
2. Skips anything already sent (`sent.db`), then ranks by keyword relevance (+ HN popularity).
3. Downloads the top articles, strips them to readable text, keeps diagrams/images, and skips short posts.
4. Bundles them into one EPUB and emails it to your Send-to-Kindle address.

## Setup
```bash
pip install -r requirements.txt
```

1. In Amazon: *Manage Your Content and Devices → Preferences → Personal Document Settings*.
   Note your **Send-to-Kindle email** and add your sender address to **Approved Personal Document E-mail List**.
2. Set SMTP credentials as environment variables (Gmail: use an [app password](https://myaccount.google.com/apppasswords)):

```bash
export KINDLE_EMAIL=you_xxxx@kindle.com
export SMTP_HOST=smtp.gmail.com      # SMTP_PORT defaults to 587 (465 = SSL)
export SMTP_USER=you@gmail.com
export SMTP_PASSWORD=your-app-password
# optional: FROM_EMAIL (defaults to SMTP_USER)
```

## Usage
```bash
python main.py --dry-run   # build out/system-design-digest.epub, send nothing
python main.py             # send to Kindle
python main.py -n 8        # 8 articles this time
```

Run weekly with cron: `0 8 * * 6  cd /path/to/repo && python main.py`

## Tuning
Edit `config.yaml`: add feeds, change `keywords` weights, `min_score`, `min_words`, or `max_articles`.
