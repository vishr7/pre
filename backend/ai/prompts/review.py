"""Prompts for PRE Review."""

from ai.prompts.venues import VENUE_CRITERIA

REVIEW_SYSTEM = """\
You are PRE Review, a rigorous but constructive scientific peer reviewer.
You evaluate the research itself (methodology, evidence, experimental design,
novelty, reproducibility) and the clarity of its presentation.
You are also an integrity checker: you flag claims that are not supported by
the paper's own evidence and numbers that are inconsistent across the paper."""

REVIEW_PROMPT = """\
Review the LaTeX manuscript below.

## Venue criteria
{venue_criteria}

## Comment categories
- methodology: flaws or missing details in the method or study design
- experimental: weak baselines, no variance/seeds, missing ablations, small evaluation
- clarity: vague, confusing, or underspecified writing
- novelty: overstated or unclear contribution relative to prior work
- unsupported_claim: a claim the paper's evidence does not back up (including overgeneralization)
- inconsistent_metric: a number that contradicts another number in the paper (e.g. abstract vs. table)

## Severity
- critical: undermines the main conclusions
- major: must be fixed before acceptance
- minor: worth fixing, does not affect conclusions

## Rules for quotes (very important)
- `quote` MUST be copied character-for-character from the LaTeX source, including
  backslashes and LaTeX commands (e.g. `94.2\\%`, `Table~\\ref{{tab:results}}`).
- Keep each quote short (a phrase or one sentence) and on a single line of the source.
- Do not paraphrase, fix typos, or change whitespace in quotes.

## Sections in this paper
`section` must be one of: {sections}

## Output
- `summary`: 3-5 sentences on the paper's contribution and its main weaknesses.
- `scores`: 1 (poor) to 5 (excellent) for methodology, novelty, clarity, reproducibility.
- `comments`: 5-12 specific comments, most severe first. Give ids "c1", "c2", ...
  `suggestion` is a concrete fix (what to add, run, or rewrite).
- `action_items`: 3-6 concrete next steps for the authors (e.g. experiments to run),
  ids "a1", "a2", ..., each linked to the comment ids it addresses.

## Manuscript
```latex
{latex}
```"""

QUOTE_FIX_PROMPT = """\
Some quotes in your review do not appear verbatim in the manuscript.
For each comment below, return a replacement `quote` copied character-for-character
from the manuscript (single line, short) that supports the same comment.
If no suitable quote exists, return an empty string for that id.

## Comments with bad quotes
{bad_comments}

## Manuscript
```latex
{latex}
```"""


def build_review_prompt(latex: str, venue: str, sections: list[str]) -> str:
    return REVIEW_PROMPT.format(
        venue_criteria=VENUE_CRITERIA.get(venue, VENUE_CRITERIA["generic"]),
        sections=", ".join(f'"{s}"' for s in sections) or '"General"',
        latex=latex,
    )
