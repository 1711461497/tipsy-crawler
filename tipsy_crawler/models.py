"""Pydantic models for crawler data."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class CharacterMeta(BaseModel):
    """Metadata extracted from an author profile card."""

    name: str
    chat_id: str
    cover_url: str
    profile_url: str
    author_uid: str
    author_name: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class RawCharacter(BaseModel):
    """Raw character data extracted from a public chat page."""

    chat_id: str
    name: str
    title: Optional[str] = None
    backstory: str = ""
    opening: str = ""
    tags: List[str] = Field(default_factory=list)
    main_character_images: List[str] = Field(default_factory=list)
    cover_url: str
    source_url: str
    language: str = "en"
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class WashedCharacter(BaseModel):
    """Character after text washing (name replacement + light rewrite)."""

    chat_id: str
    original_name: str
    new_name: str
    backstory: str
    opening: str
    tags: List[str] = Field(default_factory=list)
    cover_path: Optional[Path] = None
    washed_at: datetime = Field(default_factory=datetime.utcnow)


class TavernV2Card(BaseModel):
    """Tavern AI V2 character card output."""

    spec: str = "chara_card_v2"
    spec_version: str = "2.0"
    data: Dict[str, Any]


class AuthorInfo(BaseModel):
    """Author metadata index entry."""

    uid: str
    name: str
    url: str
    character_count: int
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRecord(BaseModel):
    """Scraped chat page content (character messages only)."""

    chat_id: str
    character_name: str
    messages: List[str] = Field(default_factory=list)
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
