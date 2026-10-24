"""Exact-quote anchoring. Every quote/old_text must appear verbatim in the LaTeX."""

import re

MIN_QUOTE_LEN = 4

_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")


def is_anchored(quote: str, latex: str) -> bool:
    """True if `quote` is a non-trivial verbatim substring of `latex`."""
    return len(quote.strip()) >= MIN_QUOTE_LEN and quote in latex


def extract_sections(latex: str) -> list[str]:
    sections = _SECTION_RE.findall(latex)
    if "\\begin{abstract}" in latex:
        sections.insert(0, "Abstract")
    return sections
