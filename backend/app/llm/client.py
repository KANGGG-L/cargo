"""OpenAI-compatible LLM adapter.

Works with any OpenAI-compatible endpoint — GLM, DeepSeek, OpenAI, or a local
Ollama server (http://localhost:11434/v1) — selected purely via settings.
"""

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings
from app.llm.events import StreamEnd, StreamEvent, TextDelta, ToolCallChunk


class LiveLLM:
    def __init__(self, settings: Settings):
        self.model = settings.llm_model
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta is not None:
                if delta.content:
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    yield ToolCallChunk(
                        index=tc.index,
                        call_id=tc.id,
                        name=tc.function.name if tc.function else None,
                        arguments_delta=tc.function.arguments if tc.function else "",
                    )
            if choice.finish_reason:
                yield StreamEnd(choice.finish_reason)

    async def complete_text(self, system: str, user: str, question_hint: str | None = None) -> str:
        res = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        content = res.choices[0].message.content or ""
        return content.strip()


def get_llm() -> "LiveLLM | MockLLM":
    """Return the live OpenAI-compatible client, or the offline mock when no key is set."""
    from app.config import get_settings, is_mock_mode

    if is_mock_mode():
        from app.llm.mock import MockLLM

        return MockLLM()
    return LiveLLM(get_settings())
