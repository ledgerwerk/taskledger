"""Safe Markdown-to-HTML renderer for task reports.

Uses markdown-it-py with raw HTML disabled so that user-controlled content
like ``<script>`` tags is escaped rather than passed through.
"""

from __future__ import annotations

import re
from functools import lru_cache

from markdown_it import MarkdownIt
from markupsafe import Markup

_HEADING_IDS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Description", "description"),
    ("Relationships", "relationships"),
    ("Requirements", "requirements"),
    ("Linked Files", "files"),
    ("Questions", "questions"),
    ("Plans", "plans"),
    ("Accepted Plan", "accepted-plan"),
    ("Acceptance Criteria", "acceptance-criteria"),
    ("Todo Checklist", "todos"),
    ("Implementation", "implementation"),
    ("Checks", "checks"),
    ("Code Reviews", "code-reviews"),
    ("Code Changes", "changes"),
    ("Command Transcript", "command-log"),
    ("Validation", "validation"),
    ("Lock State", "locks"),
    ("Events", "events"),
    ("Next Action", "next-action"),
)


@lru_cache(maxsize=1)
def _markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False})
    # Tables and strikethrough are useful for task report tables when
    # supported by the installed markdown-it-py version.
    for rule in ("table", "strikethrough"):
        try:
            md.enable(rule)
        except ValueError:
            pass
    return md


def render_markdown_html(markdown_text: str) -> Markup:
    """Render *markdown_text* to safe HTML.

    Returns a :class:`markupsafe.Markup` instance so Jinja autoescape
    treats it as already-escaped content.
    """
    html = _markdown().render(markdown_text or "")
    html = _add_known_heading_ids(html)
    return Markup(html)


def _add_known_heading_ids(html: str) -> str:
    """Annotate the first ``<h2>`` for each known report section with an id."""
    for heading, section_id in _HEADING_IDS:
        pattern = re.compile(rf"<h2>{re.escape(heading)}</h2>")
        html = pattern.sub(f'<h2 id="{section_id}">{heading}</h2>', html, count=1)
    return html
