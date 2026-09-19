from __future__ import annotations

from typing import Protocol

from app.core.config import Settings


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int, temperature: float) -> str: ...

    def describe_image(self, image_bytes: bytes, media_type: str, prompt: str, max_tokens: int) -> str: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def describe_image(self, image_bytes: bytes, media_type: str, prompt: str, max_tokens: int) -> str:
        import base64

        encoded = base64.standard_b64encode(image_bytes).decode("utf-8")
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": encoded},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMNotConfiguredError(
                "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set"
            )
        return AnthropicLLMClient(api_key=settings.anthropic_api_key, model=settings.llm_model)
    raise LLMNotConfiguredError(f"Unknown llm_provider: {settings.llm_provider!r}")
