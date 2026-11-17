# sysdigest

Finds the **best** system design reads anywhere on the web and emails them to your Kindle as one EPUB.

- **No source list.** Hacker News and Lobste.rs are used only as discovery engines: they link to
  any site, and their votes are a quality signal. Both recent posts and all-time classics are searched.
- **Best only, never padded.** `max_articles` is a ceiling, not a target. If only two articles clear
  the bar, you get two; if none do, nothing is sent.
- **Never repeats.** Everything sent is recorded in `sent.db`.

## How articles are chosen
1. **On-topic:** the title must match system design keywords (popularity alone never qualifies).
2. **Community-vetted:** at least 150 HN points for recent posts, 500 for classics, or 20 on Lobsters.
3. **Long-form:** at least 1,200 words; diagrams, code and structure score extra.
4. **Claude editor (optional, recommended):** Claude reads each finalist in full and grades it
   harshly out of 10. Only articles scoring 8+ that are really about system design are sent, and its
   one-line "why it's worth reading" appears at the top of each chapter.
   Without Anthropic credentials, a heuristic bar (relevance + votes + depth) is used instead.
5. At most one article per site per digest.

## Setup
```bash
pip install -r requirements.txt
```

1. In Amazon: *Manage Your Content and Devices → Preferences → Personal Document Settings*.
   Note your **Send-to-Kindle email** and add your sender address to the
   **Approved Personal Document E-mail List**.
2. Set environment variables (Gmail: use an [app password](https://myaccount.google.com/apppasswords)):

```bash
export KINDLE_EMAIL=you_xxxx@kindle.com
export SMTP_HOST=smtp.gmail.com      # SMTP_PORT defaults to 587 (465 = SSL)
export SMTP_USER=you@gmail.com
export SMTP_PASSWORD=your-app-password
export ANTHROPIC_API_KEY=sk-ant-...  # optional: turns on the Claude editor
```

Grading costs roughly $0.20–0.60 per run with the default `candidate_pool: 30`.

## Usage
```bash
python main.py --dry-run   # build out/system-design-digest-<date>.epub, send nothing
python main.py             # send to Kindle
python main.py -n 3        # at most 3 articles this time
```

Run weekly with cron: `0 8 * * 6  cd /path/to/repo && python main.py`

## Tuning (`config.yaml`)
- Stricter/looser: `quality.min_claude_score`, `quality.min_heuristic_score`, `min_words`
- Discovery: HN `queries`, point thresholds, `classics_years`; Lobsters `tags`
- What counts as system design: `keywords` / `negative_keywords`

## Tests
```bash
python -m pytest -q    # offline; no network, SMTP or API key needed
```
