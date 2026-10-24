"""Tests for review quote anchoring using a fake Gemini client (no API key needed)."""

import json
from types import SimpleNamespace

import pytest

from ai import gemini
from ai.anchors import extract_sections, is_anchored
from ai.review import review_paper
from ai.schemas import ReviewRequest

LATEX = r"""\begin{abstract}
We reach 94.2\% accuracy.
\end{abstract}
\section{Experiments}
Each model was trained once.
"""


def comment(id, quote):
    return {
        "id": id, "section": "Experiments", "quote": quote, "category": "experimental",
        "severity": "major", "comment": "x", "suggestion": "y",
    }


def review_json(comments):
    return json.dumps({
        "summary": "s",
        "scores": {"methodology": 2, "novelty": 3, "clarity": 4, "reproducibility": 1},
        "comments": comments,
        "action_items": [{"id": "a1", "title": "t", "description": "d",
                          "related_comment_ids": [c["id"] for c in comments]}],
    })


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        return SimpleNamespace(text=self.replies.pop(0))


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        models = FakeModels(replies)
        monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=models))
        monkeypatch.setenv("GEMINI_MODEL", "test-model")
        return models
    return install


def test_is_anchored():
    assert is_anchored(r"94.2\%", LATEX)
    assert not is_anchored("94.2%", LATEX)  # missing LaTeX escape
    assert not is_anchored("", LATEX)
    assert not is_anchored("  ", LATEX)


def test_extract_sections():
    assert extract_sections(LATEX) == ["Abstract", "Experiments"]


def test_all_quotes_valid_no_retry(fake):
    models = fake(review_json([comment("c1", "Each model was trained once.")]))
    out = review_paper(ReviewRequest(latex=LATEX))
    assert [c.id for c in out.comments] == ["c1"]
    assert models.calls == 1


def test_bad_quote_fixed_on_retry(fake):
    models = fake(
        review_json([comment("c1", "Each model was trained once."),
                     comment("c2", "We reach 94.2% accuracy.")]),
        json.dumps({"fixes": [{"id": "c2", "quote": r"We reach 94.2\% accuracy."}]}),
    )
    out = review_paper(ReviewRequest(latex=LATEX))
    assert [c.id for c in out.comments] == ["c1", "c2"]
    assert models.calls == 2


def test_unfixable_quote_dropped_and_unlinked(fake):
    still_bad = json.dumps({"fixes": [{"id": "c2", "quote": "nope not here"}]})
    models = fake(
        review_json([comment("c1", "Each model was trained once."),
                     comment("c2", "invented quote")]),
        still_bad, still_bad,
    )
    out = review_paper(ReviewRequest(latex=LATEX))
    assert [c.id for c in out.comments] == ["c1"]
    assert out.action_items[0].related_comment_ids == ["c1"]
    assert models.calls == 3  # 1 review + 2 retries max
