"""Tests for structured_call using a fake Gemini client (no API key needed)."""

from types import SimpleNamespace

import pytest

from ai import gemini
from ai.schemas import EditResponse


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(text=self.replies.pop(0))


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        models = FakeModels(replies)
        monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=models))
        monkeypatch.setenv("GEMINI_MODEL", "test-model")
        return models
    return install


VALID = '{"edits": [{"old_text": "a", "new_text": "b", "reason": "r"}]}'


def test_valid_first_try(fake):
    models = fake(VALID)
    out = gemini.structured_call("prompt", EditResponse)
    assert out.edits[0].new_text == "b"
    assert len(models.prompts) == 1


def test_retries_with_error_feedback(fake):
    models = fake("not json", VALID)
    out = gemini.structured_call("prompt", EditResponse)
    assert out.edits[0].old_text == "a"
    assert "previous response was invalid" in models.prompts[1]


def test_gives_up_after_max_retries(fake):
    fake('{"edits": "nope"}', "{}", "[]")
    with pytest.raises(gemini.GeminiError):
        gemini.structured_call("prompt", EditResponse)


def test_missing_model_env(monkeypatch):
    monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=None))
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(gemini.GeminiError, match="GEMINI_MODEL"):
        gemini.structured_call("prompt", EditResponse)
