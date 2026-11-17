"""Optional Claude 'editor' that reads each candidate and grades it like a picky curator.

Enabled when Anthropic credentials are available (ANTHROPIC_API_KEY, or an
`ant auth login` profile). Without them, sysdigest falls back to heuristics.
"""
import os
from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

SYSTEM = """You are the editor of a very selective system design reading list for a \
working software engineer. You read an article and decide whether it is genuinely one of \
the best reads on system design: architecture of real systems, distributed systems, \
databases and storage, scaling, reliability, performance, and incident postmortems with \
real technical depth.

Grade harshly. A 9-10 is something an experienced engineer would bookmark and recommend: \
concrete design decisions, trade-offs, numbers, failure modes, lessons that transfer. \
7-8 is solid but ordinary. Score 5 or below for: product announcements or marketing, \
shallow listicles or beginner explainers, news, opinion without technical substance, \
anything mostly about a vendor's product, or articles that aren't really about \
system design."""


class Verdict(BaseModel):
    is_system_design: bool = Field(description="Is this really about designing/operating software systems?")
    score: int = Field(description="Quality as a system design read, 1-10")
    why: str = Field(description="One sentence a reader would see: what they'll learn and why it's worth it")


def available():
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


class Judge:
    def __init__(self, model):
        import anthropic  # imported lazily so the heuristic mode needs no SDK

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def grade(self, article):
        """Returns a Verdict, or None if the call failed or was declined."""
        text = BeautifulSoup(article["html"], "lxml").get_text("\n")
        prompt = (f"Title: {article['title']}\nURL: {article['url']}\n"
                  f"Community: {article['points']} points on {article['source']}\n\n"
                  f"<article>\n{text}\n</article>")
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM,
                output_config={"effort": "medium"},
                messages=[{"role": "user", "content": prompt}],
                output_format=Verdict,
            )
        except self.anthropic.APIStatusError as e:
            print(f"  ! judge API error ({e.status_code}) for {article['url']}: {e.message}")
            return None
        except self.anthropic.APIConnectionError as e:
            print(f"  ! judge connection error: {e}")
            return None
        if resp.stop_reason == "refusal":
            return None
        return resp.parsed_output
