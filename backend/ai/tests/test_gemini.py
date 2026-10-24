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


class OverloadedModels(FakeModels):
    """Fails with 503 for `bad_model`, answers normally otherwise."""

    def __init__(self, replies, bad_model):
        super().__init__(replies)
        self.bad_model = bad_model
        self.models_used = []

    def generate_content(self, model, contents, config):
        self.models_used.append(model)
        if model == self.bad_model:
            raise gemini.errors.APIError(503, {"error": {"message": "high demand"}})
        return super().generate_content(model, contents, config)


def test_falls_back_on_overload(monkeypatch):
    models = OverloadedModels([VALID], bad_model="main")
    monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=models))
    monkeypatch.setenv("GEMINI_MODEL", "main")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "backup")
    out = gemini.structured_call("prompt", EditResponse)
    assert out.edits[0].new_text == "b"
    assert models.models_used == ["main", "backup"]


def test_api_error_without_fallback_is_gemini_error(monkeypatch):
    models = OverloadedModels([], bad_model="main")
    monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=models))
    monkeypatch.setenv("GEMINI_MODEL", "main")
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    with pytest.raises(gemini.GeminiError, match="503"):
        gemini.structured_call("prompt", EditResponse)


def test_missing_model_env(monkeypatch):
    monkeypatch.setattr(gemini, "_client", SimpleNamespace(models=None))
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(gemini.GeminiError, match="GEMINI_MODEL"):
        gemini.structured_call("prompt", EditResponse)
