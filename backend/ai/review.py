"""PRE Review: AI scientific reviewer with exact-quote anchored comments."""

from pydantic import BaseModel

from ai.anchors import extract_sections, is_anchored
from ai.gemini import MAX_RETRIES, structured_call
from ai.prompts.review import QUOTE_FIX_PROMPT, REVIEW_SYSTEM, build_review_prompt
from ai.schemas import ReviewRequest, ReviewResponse


class QuoteFix(BaseModel):
    id: str
    quote: str


class QuoteFixes(BaseModel):
    fixes: list[QuoteFix]


def review_paper(req: ReviewRequest) -> ReviewResponse:
    prompt = build_review_prompt(req.latex, req.venue, extract_sections(req.latex))
    review = structured_call(prompt, ReviewResponse, system=REVIEW_SYSTEM)

    # Re-prompt only for comments whose quote isn't verbatim in the paper.
    for _ in range(MAX_RETRIES):
        bad = [c for c in review.comments if not is_anchored(c.quote, req.latex)]
        if not bad:
            break
        bad_comments = "\n".join(
            f'- id={c.id} section="{c.section}" quote="{c.quote}" comment="{c.comment}"'
            for c in bad
        )
        fixes = structured_call(
            QUOTE_FIX_PROMPT.format(bad_comments=bad_comments, latex=req.latex),
            QuoteFixes,
            system=REVIEW_SYSTEM,
        )
        new_quotes = {f.id: f.quote for f in fixes.fixes}
        for c in bad:
            if c.id in new_quotes:
                c.quote = new_quotes[c.id]

    return _drop_unanchored(review, req.latex)


def _drop_unanchored(review: ReviewResponse, latex: str) -> ReviewResponse:
    review.comments = [c for c in review.comments if is_anchored(c.quote, latex)]
    kept_ids = {c.id for c in review.comments}
    for item in review.action_items:
        item.related_comment_ids = [i for i in item.related_comment_ids if i in kept_ids]
    return review
