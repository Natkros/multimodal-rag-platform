from __future__ import annotations

from app.core.config import get_settings
from app.services.generation import vision_describer
from app.services.generation.llm_client import LLMNotConfiguredError


class FakeLLMClient:
    def __init__(self, response: str = "A bar chart showing quarterly revenue."):
        self.response = response
        self.calls = []

    def describe_image(self, image_bytes, media_type, prompt, max_tokens):
        self.calls.append((media_type, prompt, max_tokens))
        return self.response

    def complete(self, system, user, max_tokens, temperature):
        raise NotImplementedError


class FailingLLMClient:
    def describe_image(self, *args, **kwargs):
        raise RuntimeError("upstream API error")

    def complete(self, *args, **kwargs):
        raise NotImplementedError


def test_describe_image_returns_none_when_disabled():
    settings = get_settings().model_copy(update={"vision_description_enabled": False})
    assert vision_describer.describe_image(b"fake bytes", "PNG", settings) is None


def test_describe_image_returns_none_for_unsupported_format():
    settings = get_settings().model_copy(update={"vision_description_enabled": True})
    assert vision_describer.describe_image(b"fake bytes", "TIFF", settings) is None


def test_describe_image_returns_none_when_llm_not_configured(monkeypatch):
    settings = get_settings().model_copy(update={"vision_description_enabled": True})

    def raise_not_configured(_settings):
        raise LLMNotConfiguredError("no key")

    monkeypatch.setattr(vision_describer, "get_llm_client", raise_not_configured)
    assert vision_describer.describe_image(b"fake bytes", "PNG", settings) is None


def test_describe_image_returns_caption_when_configured(monkeypatch):
    settings = get_settings().model_copy(update={"vision_description_enabled": True})
    fake_client = FakeLLMClient()

    monkeypatch.setattr(vision_describer, "get_llm_client", lambda _settings: fake_client)
    result = vision_describer.describe_image(b"fake bytes", "PNG", settings)

    assert result == "A bar chart showing quarterly revenue."
    assert fake_client.calls[0][0] == "image/png"


def test_describe_image_returns_none_on_llm_failure(monkeypatch):
    settings = get_settings().model_copy(update={"vision_description_enabled": True})
    monkeypatch.setattr(vision_describer, "get_llm_client", lambda _settings: FailingLLMClient())
    assert vision_describer.describe_image(b"fake bytes", "PNG", settings) is None


def test_describe_image_strips_whitespace_only_response_to_none(monkeypatch):
    settings = get_settings().model_copy(update={"vision_description_enabled": True})
    monkeypatch.setattr(vision_describer, "get_llm_client", lambda _settings: FakeLLMClient(response="   "))
    assert vision_describer.describe_image(b"fake bytes", "PNG", settings) is None
