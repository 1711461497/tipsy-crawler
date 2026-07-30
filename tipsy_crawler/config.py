"""Configuration loading for the crawler."""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} in strings."""
    pattern = re.compile(r"\$\{([^}:-]+)(?::-([^}]*))?\}")

    def replacer(value: str) -> str:
        def expand(match: re.Match) -> str:
            var, default = match.groups()
            return os.getenv(var, default or "")
        return pattern.sub(expand, value)

    if isinstance(obj, str):
        return replacer(obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    return obj


class LLMProviderConfig(BaseModel):
    """Single LLM provider configuration."""

    base_url: str
    api_key: str
    default_model: str
    timeout: int = 60


class TaskConfig(BaseModel):
    """Task-to-provider mapping."""

    provider: str
    model: Optional[str] = None


class MuleRouterConfig(BaseModel):
    """MuleRouter image editing configuration."""

    base_url: str = "https://api.mulerouter.ai"
    api_key: str
    image_model: str = "qwen-image-edit-spicy"
    poll_interval: int = 3
    max_poll_time: int = 300


class CrawlerConfig(BaseModel):
    """Runtime crawler behavior."""

    output_dir: Path
    author_concurrency: int = 3
    character_concurrency: int = 5
    request_delay_ms: int = 1000
    max_retries: int = 3
    headless: bool = True
    use_stealth: bool = True
    proxy_pool: list[str] = Field(default_factory=list)


class SkillHookConfig(BaseModel):
    """Skill hook extension points."""

    infer_json: list[str] = Field(default_factory=list)
    text_wash: list[str] = Field(default_factory=list)
    image_wash: list[str] = Field(default_factory=list)


class PromptsConfig(BaseModel):
    """All LLM prompts — edit config.yaml to customize."""

    name_generation_system: str = "You generate concise, immersive character names. Respond with only the new full name, no explanation."
    name_generation_user: str = "Original name: {original_name}\nBackstory excerpt: {backstory}\n\nCreate a new full name (first + last) that preserves gender, species or ethnicity flavor, and fantasy/sci-fi tone if present."

    image_prompt_system: str = (
        "You write concise image editing prompts for an AI image editor. "
        "The goal is to slightly alter a character's avatar so it looks different "
        "from the original while still fitting the character's personality and aesthetic. "
        "Rules:\n- NEVER use pink or pastel pink hair.\n"
        "- Pick hair/outfit colors that match the character's vibe.\n"
        "- Keep changes subtle.\n- Keep pose, face structure, expression, and background unchanged.\n"
        "- Output a single English sentence, no explanation."
    )
    image_prompt_user: str = "Character name: {name}\nBackstory excerpt: {backstory}\n\nWrite one image editing prompt for this character."

    wash_text_system: str = (
        "You are a creative editor. Replace every occurrence of the old character name "
        "with the new name, adjust relationship pronouns only when necessary, and lightly "
        "rewrite to avoid verbatim copy. Preserve NSFW tone, style, and {{User}}/{{Char}} "
        "placeholders. Return JSON with keys: backstory, opening."
    )
    wash_text_user: str = "Old name: {original_name}\nNew name: {new_name}\n\nBACKSTORY:\n{backstory}\n\nOPENING:\n{opening}"

    infer_card_system: str = (
        "You are a character card author. Produce a complete Tavern AI character card "
        "in chara_card_v2 'data' object format. Include name, description, personality, "
        "first_mes, scenario, mes_example, creator_notes, system_prompt, "
        "post_history_instructions, tags, alternate_greetings, creator. "
        "Keep explicit NSFW content if present. Return valid JSON only."
    )
    infer_card_user: str = "Character name: {name}\nTags: {tags}\n\nBACKSTORY:\n{backstory}\n\nOPENING (first_mes):\n{opening}\n\nAvatar filename: {image_filename}"

    infer_from_chat_system: str = (
        "You are a character card author. Analyze the following character messages "
        "from a chat page and produce a complete Tavern AI character card in "
        "chara_card_v2 'data' object format. Extract and infer: name, description, "
        "personality, first_mes, scenario, mes_example, creator_notes, system_prompt, "
        "post_history_instructions, tags, alternate_greetings, creator. "
        "Keep explicit NSFW content if present. Return valid JSON only."
    )
    infer_from_chat_user: str = "Character name: {character_name}\n\nCHARACTER MESSAGES:\n{chat_text}"


class AppConfig(BaseSettings):
    """Application settings loaded from YAML and env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
    mule_router: MuleRouterConfig = Field(default_factory=lambda: MuleRouterConfig(api_key=""))
    crawler: CrawlerConfig = Field(
        default_factory=lambda: CrawlerConfig(
            output_dir=Path("/Users/akb/.qoderwork/tipsy-crawler/output")
        )
    )
    skill_hooks: SkillHookConfig = Field(default_factory=SkillHookConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "AppConfig":
        """Load configuration from a YAML file."""
        load_dotenv()  # Load .env file into os.environ
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw = _expand_env_vars(raw)
        return cls(**raw)


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from file or return defaults."""
    if path and path.exists():
        return AppConfig.from_yaml(path)
    return AppConfig()
