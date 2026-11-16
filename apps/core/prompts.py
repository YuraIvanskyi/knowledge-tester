"""The AI prompts shown on the Help page.

The text lives in one place, docs/llm/test-from-textbook.uk.prompt.md (readable on its own and
checked by a test against the importer). This module only cuts the copy-and-paste parts out of
that file: the main prompt is its one four-backtick ``text`` block, and every follow-up request
is a bold title followed by a three-backtick ``text`` block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from django.conf import settings

PROMPT_FILE = Path("docs") / "llm" / "test-from-textbook.uk.prompt.md"

_MAIN = re.compile(r"^````text\n(.*?)\n````$", re.DOTALL | re.MULTILINE)
_FOLLOW_UP = re.compile(r"^\*\*(.+?):?\*\*:?\s*\n\n```text\n(.*?)\n```$", re.DOTALL | re.MULTILINE)


@dataclass(frozen=True)
class FollowUp:
    title: str
    text: str


@dataclass(frozen=True)
class PromptPack:
    prompt: str = ""
    follow_ups: list[FollowUp] = field(default_factory=list)
    path: Path = PROMPT_FILE


def parse(markdown: str) -> PromptPack:
    markdown = markdown.replace("\r\n", "\n")
    main = _MAIN.search(markdown)
    rest = markdown[main.end() :] if main else markdown
    follow_ups = [
        FollowUp(title.strip().rstrip(":"), text.strip())
        for title, text in _FOLLOW_UP.findall(rest)
    ]
    return PromptPack(main.group(1).strip() if main else "", follow_ups)


@lru_cache(maxsize=1)
def textbook_prompt() -> PromptPack:
    """The prompt pack, or an empty one when the file is missing (the page then says where it
    should be)."""
    try:
        return parse((settings.BASE_DIR / PROMPT_FILE).read_text(encoding="utf-8"))
    except OSError:
        return PromptPack()
