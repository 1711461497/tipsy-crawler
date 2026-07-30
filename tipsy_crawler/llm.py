"""Switchable LLM provider abstraction for text tasks."""

import asyncio
import json
import re
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import AppConfig, TaskConfig


def _safe_json_parse(text: str) -> dict:
    """Parse JSON from LLM output, handling common formatting issues."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fixed = re.sub(r",\s*}", "}", text)
    fixed = re.sub(r",\s*]", "]", fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            extracted = match.group()
            extracted = re.sub(r",\s*}", "}", extracted)
            extracted = re.sub(r",\s*]", "]", extracted)
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("Unable to parse JSON from LLM response", text[:500], 0)


class LLMClient:
    """Generic OpenAI-compatible LLM client."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.p = config.prompts  # shortcut for prompt access

    def _resolve(self, task: str) -> tuple[TaskConfig, Any]:
        task_cfg = self.config.tasks.get(task)
        if not task_cfg:
            raise ValueError(f"No task config found for '{task}'")
        provider_cfg = self.config.providers.get(task_cfg.provider)
        if not provider_cfg:
            raise ValueError(f"No provider config found for '{task_cfg.provider}'")
        return task_cfg, provider_cfg

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def chat(
        self,
        task: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> str:
        """Send a chat completion request for the configured task.

        Uses sync httpx in a worker thread to avoid event loop conflicts
        with Playwright (which can cause ConnectError on some systems).
        """
        task_cfg, provider = self._resolve(task)
        model = task_cfg.model or provider.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format

        def _sync_request() -> str:
            with httpx.Client(timeout=provider.timeout, trust_env=False) as client:
                resp = client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

        return await asyncio.to_thread(_sync_request)

    async def generate_name(self, original_name: str, backstory: str) -> str:
        """Generate a new character name that fits the backstory."""
        backstory_excerpt = backstory[:800] if backstory else "No backstory available."
        messages = [
            {"role": "system", "content": self.p.name_generation_system.strip()},
            {"role": "user", "content": self.p.name_generation_user.strip().format(
                original_name=original_name, backstory=backstory_excerpt,
            )},
        ]
        return (await self.chat("name_generation", messages, temperature=0.9)).strip()

    async def generate_image_prompt(self, name: str, backstory: str) -> str:
        """Generate an image-editing prompt that fits the character's persona."""
        backstory_excerpt = backstory[:600] if backstory else "No backstory available."
        messages = [
            {"role": "system", "content": self.p.image_prompt_system.strip()},
            {"role": "user", "content": self.p.image_prompt_user.strip().format(
                name=name, backstory=backstory_excerpt,
            )},
        ]
        prompt = (await self.chat("name_generation", messages, temperature=0.8)).strip()
        prompt = prompt.strip('"').strip("'")
        return prompt

    async def wash_text(
        self, original_name: str, new_name: str, backstory: str, opening: str
    ) -> tuple[str, str]:
        """Replace old name with new name and lightly rewrite the text."""
        messages = [
            {"role": "system", "content": self.p.wash_text_system.strip()},
            {"role": "user", "content": self.p.wash_text_user.strip().format(
                original_name=original_name, new_name=new_name,
                backstory=backstory, opening=opening,
            )},
        ]
        response = await self.chat(
            "text_wash",
            messages,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        parsed = _safe_json_parse(response)
        return parsed.get("backstory", backstory), parsed.get("opening", opening)

    async def infer_card(self, washed: Any, image_filename: str) -> dict[str, Any]:
        """Reverse-engineer a Tavern V2 card from washed text."""
        from .models import WashedCharacter

        washed = WashedCharacter.model_validate(washed)
        messages = [
            {"role": "system", "content": self.p.infer_card_system.strip()},
            {"role": "user", "content": self.p.infer_card_user.strip().format(
                name=washed.new_name,
                tags=", ".join(washed.tags),
                backstory=washed.backstory,
                opening=washed.opening,
                image_filename=image_filename,
            )},
        ]
        response = await self.chat(
            "infer_json",
            messages,
            temperature=0.8,
            response_format={"type": "json_object"},
        )
        return _safe_json_parse(response)

    async def infer_from_chat(
        self, character_name: str, messages: list[str]
    ) -> dict[str, Any]:
        """Reverse-engineer a Tavern V2 card from chat page messages."""
        chat_text = "\n\n---\n\n".join(messages)

        messages_payload = [
            {"role": "system", "content": self.p.infer_from_chat_system.strip()},
            {"role": "user", "content": self.p.infer_from_chat_user.strip().format(
                character_name=character_name, chat_text=chat_text,
            )},
        ]
        response = await self.chat(
            "infer_json",
            messages_payload,
            temperature=0.8,
            response_format={"type": "json_object"},
        )
        return _safe_json_parse(response)
