# sysdigest

Topics: `system-design` (default) and `ai-engineering` (building with LLMs, agents, RAG, evals,
GitHub, Databricks/lakehouse...). Choose with `--topic`, e.g. `python main.py -t ai-engineering auto`.
Add your own topic by copying a block under `topics:` in `config.yaml`.

Finds the **best** system design reads anywhere on the web and emails them to your Kindle as one EPUB.

- **No source list.** Hacker News and Lobste.rs are used only as discovery engines: they link to
  any site, and their votes are a quality signal. Both recent posts and all-time classics are searched.
- **Best only, never padded.** `max_articles` is a ceiling, not a target. If only two articles clear
  the bar, you get two; if none do, nothing is sent.
- **Never repeats.** Everything sent is recorded in `sent.json`.

## How articles are chosen
1. **On-topic:** the title must match system design keywords (popularity alone never qualifies).
2. **Community-vetted:** at least 150 HN points for recent posts, 500 for classics, or 20 on Lobsters.
3. **Long-form:** at least 1,200 words; diagrams, code and structure score extra.
4. **Built-in editor** (`sysdigest/editor.py`, no LLM): reads each article's full text and judges it
   the way a careful human editor would:
   - *rejects* articles whose body isn't about software systems (e.g. "Naval Architecture"),
     security-incident write-ups, sales/marketing pages and link-index pages;
   - *scores* the rest 0–10 on how deeply they stay on systems, concrete numbers (TB, ms, req/s),
     reasoning (trade-offs, root causes) and first-hand engineering ("we measured…");
   - writes a "why read this" line by picking the most informative sentence from the opening.

   It was calibrated against hand-labelled keep/cut decisions on real candidates and agrees on 18/18.
   It's an approximation of a human editor: very good at rejecting junk, rougher at ranking
   the good articles against each other.
5. **Variety:** at most one article per site and two postmortems per digest.

## Two modes
**Automatic mode** (the built-in editor picks; nothing else needed):
```bash
python main.py auto          # build only
python main.py auto --send   # build and email (records the articles as sent)
```

**Manual editor mode** (you, or an agent such as Claude Code, make the final call; the
built-in editor's score is shown next to each candidate):
```bash
python main.py gather                    # writes out/candidates/INDEX.md + one .md per article
# read the candidates, then write picks.yaml in reading order:
#   - url: https://example.com/post
#     why: "One line on what you'll learn."
python main.py build picks.yaml          # builds out/system-design-digest-<date>.epub
python main.py build picks.yaml --send   # ...and emails it to your Kindle (records it as sent)
python main.py build picks.yaml --mark   # record as sent when delivered another way
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
- Stricter/looser: `min_editor_score`, `max_postmortems`, `min_words`, `max_articles`
- Discovery: HN `queries`, point thresholds, `classics_years`; Lobsters `tags`
- What counts as system design: `keywords` / `negative_keywords`

## Tests
```bash
python -m pytest -q    # offline; no network, SMTP or API key needed
```
