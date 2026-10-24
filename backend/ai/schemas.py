"""Pydantic schemas for PRE's AI endpoints.

These shapes are the API contract agreed with Person 1 (frontend) and
Person 4 (backend). Don't change them without telling the team.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Venue = Literal["neurips", "acl", "journal", "generic"]
Category = Literal[
    "methodology",
    "clarity",
    "experimental",
    "novelty",
    "unsupported_claim",
    "inconsistent_metric",
]
Severity = Literal["minor", "major", "critical"]


# ---------- /ai/review ----------

class ReviewRequest(BaseModel):
    latex: str
    venue: Venue = "generic"


class Scores(BaseModel):
    methodology: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    reproducibility: int = Field(ge=1, le=5)


class Comment(BaseModel):
    id: str
    section: str
    quote: str = Field(description="Exact verbatim substring of the input LaTeX")
    category: Category
    severity: Severity
    comment: str
    suggestion: str


class ActionItem(BaseModel):
    id: str
    title: str
    description: str
    related_comment_ids: list[str]


class ReviewResponse(BaseModel):
    summary: str
    scores: Scores
    comments: list[Comment]
    action_items: list[ActionItem]


# ---------- /ai/edit ----------

class EditRequest(BaseModel):
    latex: str
    instruction: str
    selection: Optional[str] = None


class Edit(BaseModel):
    old_text: str = Field(description="Exact verbatim substring of the input LaTeX")
    new_text: str
    reason: str


class EditResponse(BaseModel):
    edits: list[Edit]
