"""A local 'editor' that reads each article's full text and judges it, with no LLM.

It encodes the checks a careful human editor makes while reading:

  topic      Is the body really about software systems? (not just a title keyword)
  substance  Concrete facts: numbers with units, scale, measurements.
  reasoning  Explains why: trade-offs, root causes, decisions, lessons.
  experience First-hand engineering ("we built", "we measured") over hearsay.
  penalties  Marketing / calls to action, link-index pages, security-incident write-ups.

The weights were calibrated against hand-labelled keep/cut decisions (see README).
"""
import re

from bs4 import BeautifulSoup

TOPIC_TERMS = re.compile(r"\b(" + "|".join([
    r"servers?", r"databases?", r"cach(e|es|ing)", r"latency", r"throughput", r"replicas?",
    r"replication", r"clusters?", r"nodes?", r"shard(s|ing)?", r"partition(s|ing)?", r"queues?",
    r"requests?", r"traffic", r"storage", r"network(s|ing)?", r"failover", r"consistency",
    r"services?", r"microservices?", r"deploy(s|ed|ment|ments)?", r"regions?", r"data ?cent(er|re)s?",
    r"writes?", r"reads?", r"quorum", r"leader", r"consensus", r"load", r"load balanc\w*",
    r"memory", r"cpus?", r"disks?", r"bandwidth", r"api", r"backend", r"infrastructure",
    r"scal(e|es|ing|able|ability)", r"distributed", r"availability", r"redundan\w+",
    r"postgres\w*", r"mysql", r"redis", r"kafka", r"kubernetes", r"containers?", r"rollouts?",
    r"configuration", r"config", r"routing", r"proxy", r"index(es)?", r"transactions?",
]) + r")\b")

# A number with a unit ("50%", "73 hours", "100 terabytes") or a big count ("7,200 pushes").
QUANT = re.compile(
    r"(?<![\w.])(\d[\d,.]*\s?(%|ms|µs|ns|sec|seconds?|minutes?|hours?|days?|[kmgtp]i?b\b|"
    r"[kmgtp]bps|kilobytes?|megabytes?|gigabytes?|terabytes?|petabytes?|million|billion|"
    r"thousand|x\b|rps|qps|req/s|/s\b|per second)|\d{1,3}(,\d{3})+)(?!\w)", re.I)

REASONING = re.compile(r"\b(" + "|".join([
    r"trade-?offs?", r"instead of", r"rather than", r"because", r"the downside", r"at the cost of",
    r"we (chose|decided|opted)", r"bottlenecks?", r"root cause", r"lessons?", r"which means",
    r"so that", r"as a result", r"the problem (is|was)", r"the reason", r"in practice",
    r"failure modes?", r"mitigat\w+", r"contention",
]) + r")\b", re.I)

EXPERIENCE = re.compile(r"\b(we|our team) (built|found|noticed|measured|migrated|rewrote|"
                        r"designed|discovered|saw|learned|moved|replaced|added|ran|deployed|"
                        r"observed|identified|realized)\b", re.I)

MARKETING = re.compile(r"\b(" + "|".join([
    r"sign up", r"book a (demo|call)", r"free trial", r"get started", r"contact sales",
    r"see available times", r"subscribe now", r"request a demo",
    r"get detailed feedback", r"limited time", r"schedule a call",
]) + r")\b", re.I)

SECURITY = re.compile(r"\b(vulnerab\w+|exploit\w*|cve-\d+|malware|phishing|attackers?|"
                      r"payload|compromis\w+|malicious)\b", re.I)

BOILERPLATE = re.compile(r"\b(apologi[sz]e|sorry|credits?|sla|thank|we recogni[sz]e|"
                         r"read more|click|newsletter|update:)\b", re.I)

POSTMORTEM = re.compile(r"\b(outage|post-?mortem|incident)\b", re.I)


def _per_k(n, words):
    return 1000 * n / max(words, 1)


def features(title, html):
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    words = max(len(text.split()), 1)
    link_words = sum(len(a.get_text(" ").split()) for a in soup.find_all("a"))
    return {
        "words": words,
        "topic": _per_k(len(TOPIC_TERMS.findall(text.lower())), words),
        "quant": _per_k(len(QUANT.findall(text)), words),
        "reasoning": _per_k(len(REASONING.findall(text)), words),
        "experience": _per_k(len(EXPERIENCE.findall(text)), words),
        "marketing": len(MARKETING.findall(text)),
        "security": _per_k(len(SECURITY.findall(text)), words),
        "link_density": link_words / words,
        "postmortem": bool(POSTMORTEM.search(title)),
    }


def judge(title, html):
    """Returns (score 0-10, verdict). 0 means rejected outright, with the reason."""
    f = features(title, html)
    if f["security"] >= 5:
        return 0.0, "security incident, not system design", f
    if f["marketing"] >= 4:
        return 0.0, "marketing / sales content", f
    if f["link_density"] > 0.35:
        return 0.0, "link index page, not an article", f
    # Strongly on-topic, or moderately on-topic but dense with first-hand numbers
    # (e.g. a build story that also covers frontend/mobile, like Reddit's r/Place).
    substantive = f["quant"] >= 4 and f["experience"] >= 1
    if f["topic"] < 30 and not (f["topic"] >= 20 and substantive):
        return 0.0, "off-topic: body isn't about software systems", f
    score = (5.0
             + max(min(f["topic"] - 30, 40), 0) / 20  # how deeply it stays on systems (0-2)
             + min(f["quant"], 6) / 3             # concrete numbers (0-2)
             + min(f["reasoning"], 8) / 4         # explains why, trade-offs (0-2)
             + min(f["experience"], 2) / 2)       # first-hand engineering (0-1)
    return min(score, 10.0), "", f


_SENT = re.compile(r"(?<=[.!?])\s+")
_REPEAT = re.compile(r"\b(\w+) \1\b", re.I)  # "Storage Storage overview": heading residue


def why_line(html, max_len=220):
    """Pick the most informative sentence from the opening as a 'why read this' line."""
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ")).strip()
    sentences = [s for s in _SENT.split(" ".join(text.split()[:700])) if 60 <= len(s) <= max_len]
    if not sentences:
        return ""

    def info(s):
        words = s.split()
        caps = sum(w[:1].isupper() for w in words) / len(words)
        lead_caps = len(words) > 2 and all(w[:1].isupper() for w in words[:3])  # "Mgmtd Requests Nodes ..."
        return (2 * len(QUANT.findall(s)) + len(TOPIC_TERMS.findall(s.lower()))
                + len(REASONING.findall(s)) - 3 * len(MARKETING.findall(s))
                - 5 * len(BOILERPLATE.findall(s))
                - (6 if caps > 0.4 or lead_caps else 0)  # headings / navigation run together
                - (6 if _REPEAT.search(s) or s.count(":") > 1 else 0))
    return max(sentences, key=info)
