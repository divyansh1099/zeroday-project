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
4. **Editor review:** someone actually reads the finalists and picks only the great ones,
   adding a one-line "why it's worth reading" to each chapter. The editor can be you or an AI agent
   such as Claude Code; no LLM API is involved.

## Two modes
**Editor mode** (best quality):
```bash
python main.py gather                    # writes out/candidates/INDEX.md + one .md per article
# read the candidates, then write picks.yaml in reading order:
#   - url: https://example.com/post
#     why: "One line on what you'll learn."
python main.py build picks.yaml          # builds out/system-design-digest-<date>.epub
python main.py build picks.yaml --send   # ...and emails it to your Kindle (records it as sent)
python main.py build picks.yaml --mark   # record as sent when delivered another way
```

**Automatic mode** (no editor; a heuristic bar of relevance + votes + depth):
```bash
python main.py auto          # build only
python main.py auto --send   # build and email
```

Everything sent is recorded in `sent.json` (commit it so the history follows you).

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
```

## Scheduling
Automatic mode works with plain cron: `0 8 * * 6  cd /path/to/repo && python main.py auto --send`

## Tuning (`config.yaml`)
- Stricter/looser: `min_heuristic_score`, `min_words`, `max_articles`
- Discovery: HN `queries`, point thresholds, `classics_years`; Lobsters `tags`
- What counts as system design: `keywords` / `negative_keywords`

## Tests
```bash
python -m pytest -q    # offline; no network, SMTP or API key needed
```
