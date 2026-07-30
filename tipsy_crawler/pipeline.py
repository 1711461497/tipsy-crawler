"""End-to-end pipeline orchestration."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from .config import AppConfig
from .downloader import _ext_from_url
from .image_wash import ImageWasher, placeholder_wash
from .llm import LLMClient
from .models import AuthorInfo, CharacterMeta, RawCharacter, WashedCharacter
from .scraper import TipsyScraper


class CrawlPipeline:
    """Orchestrates scan → fetch → download → wash → infer → archive."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.output_dir = config.crawler.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run_mvp(
        self,
        author_urls: list[str],
        max_chars: int = 3,
        wash_images: bool = False,
        wash_text: bool = False,
        infer_json: bool = False,
    ) -> None:
        """Run a minimal end-to-end scrape for the given authors.

        Split into two phases to avoid Playwright/httpx conflicts:
        Phase 1 (browser): scan authors + fetch pages + download covers
        Phase 2 (API): wash images + wash text + infer JSON
        """
        # Phase 1: Browser operations
        fetched: list[tuple[CharacterMeta, RawCharacter, Optional[Path]]] = []
        async with TipsyScraper(
            headless=self.config.crawler.headless,
            use_stealth=self.config.crawler.use_stealth,
            request_delay_ms=self.config.crawler.request_delay_ms,
        ) as scraper:
            all_meta: list[CharacterMeta] = []
            authors: list[AuthorInfo] = []

            for url in author_urls:
                info, chars = await scraper.scan_author(url)
                authors.append(info)
                all_meta.extend(chars)
                print(f"[scan] {info.uid}: {info.character_count} characters")
                await asyncio.sleep(self.config.crawler.request_delay_ms / 1000)

            self._save_authors_index(authors)

            # Limit for MVP
            selected = all_meta[:max_chars]
            for meta in selected:
                try:
                    # Fetch + download while browser is open
                    raw, cover_path = await self._fetch_character(scraper, meta)
                    fetched.append((meta, raw, cover_path))
                except Exception as exc:
                    print(f"[error] {meta.name} ({meta.chat_id}): {exc}")
                    import traceback
                    traceback.print_exc()
                    continue
                await asyncio.sleep(self.config.crawler.request_delay_ms / 1000)

        # Browser is now closed — Phase 2: API operations
        for meta, raw, cover_path in fetched:
            try:
                char_dir = self.output_dir / meta.author_uid / meta.chat_id
                await self._process_character_api(
                    raw, char_dir, cover_path, wash_images, wash_text, infer_json
                )
            except Exception as exc:
                print(f"[error] {raw.name} ({raw.chat_id}): {exc}")
                import traceback
                traceback.print_exc()
                continue

    async def _fetch_character(
        self,
        scraper: TipsyScraper,
        meta: CharacterMeta,
    ) -> tuple[RawCharacter, Optional[Path]]:
        """Fetch raw data and download cover (browser phase only)."""
        char_dir = self.output_dir / meta.author_uid / meta.chat_id
        raw_dir = char_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        print(f"[fetch] {meta.name} ({meta.chat_id})")
        raw = await scraper.fetch_character(meta.chat_id)
        if meta.cover_url:
            raw.cover_url = meta.cover_url

        # Save raw text
        (raw_dir / "backstory.txt").write_text(raw.backstory, encoding="utf-8")
        (raw_dir / "opening.txt").write_text(raw.opening, encoding="utf-8")
        (raw_dir / "meta.json").write_text(
            raw.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Download cover
        cover_path = None
        if raw.cover_url:
            cover_dest = raw_dir / "cover_image"
            try:
                cover_path = await scraper.download_with_browser(raw.cover_url, cover_dest)
                ext = _ext_from_url(raw.cover_url) or ".jpg"
                if cover_path.suffix != ext:
                    new_path = cover_path.with_suffix(ext)
                    cover_path.rename(new_path)
                    cover_path = new_path
                print(f"[download] {cover_path.name}")
            except Exception as exc:
                print(f"[download error] {meta.chat_id}: {exc}")

        return raw, cover_path

    def _save_authors_index(self, authors: list[AuthorInfo]) -> None:
        """Write authors.json index to output root."""
        path = self.output_dir / "authors.json"
        data = [a.model_dump(mode="json") for a in authors]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    async def run_char_urls(
        self,
        char_urls: list[str],
        wash_images: bool = False,
        wash_text: bool = False,
        infer_json: bool = False,
    ) -> None:
        """Process specific character URLs through the full pipeline.

        Split into two phases to avoid Playwright/httpx event loop conflicts:
        Phase 1 (browser): fetch pages + download covers
        Phase 2 (API): wash images + wash text + infer JSON
        """
        import re

        # Phase 1: Browser operations — fetch + download
        fetched: list[tuple[CharacterMeta, RawCharacter, Optional[Path]]] = []
        async with TipsyScraper(
            headless=self.config.crawler.headless,
            use_stealth=self.config.crawler.use_stealth,
            request_delay_ms=self.config.crawler.request_delay_ms,
        ) as scraper:
            for url in char_urls:
                match = re.search(r"/chat/(\d+)", url)
                if not match:
                    print(f"[error] Cannot extract chat_id from: {url}")
                    continue
                chat_id = match.group(1)
                try:
                    raw = await scraper.fetch_character(chat_id)
                    author_uid = "direct"
                    cover_match = re.search(r"/(\d{10,})_", raw.cover_url or "")
                    if cover_match:
                        author_uid = cover_match.group(1)

                    meta = CharacterMeta(
                        name=raw.name,
                        chat_id=chat_id,
                        cover_url=raw.cover_url,
                        profile_url="",
                        author_uid=author_uid,
                    )

                    # Save raw data + download cover while browser is open
                    char_dir = self.output_dir / author_uid / chat_id
                    raw_dir = char_dir / "raw"
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / "backstory.txt").write_text(raw.backstory, encoding="utf-8")
                    (raw_dir / "opening.txt").write_text(raw.opening, encoding="utf-8")
                    (raw_dir / "meta.json").write_text(
                        raw.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
                    )

                    cover_path = None
                    if raw.cover_url:
                        from .downloader import _ext_from_url
                        cover_dest = raw_dir / "cover_image"
                        try:
                            cover_path = await scraper.download_with_browser(raw.cover_url, cover_dest)
                            ext = _ext_from_url(raw.cover_url) or ".jpg"
                            if cover_path.suffix != ext:
                                new_path = cover_path.with_suffix(ext)
                                cover_path.rename(new_path)
                                cover_path = new_path
                            print(f"[download] {cover_path.name}")
                        except Exception as exc:
                            print(f"[download error] {chat_id}: {exc}")

                    print(f"[fetch] {raw.name} ({chat_id})")
                    fetched.append((meta, raw, cover_path))
                except Exception as exc:
                    print(f"[error] chat {chat_id}: {exc}")
                    import traceback
                    traceback.print_exc()
                    continue
                await asyncio.sleep(self.config.crawler.request_delay_ms / 1000)

        # Browser is now closed — Phase 2: API operations
        for meta, raw, cover_path in fetched:
            try:
                char_dir = self.output_dir / meta.author_uid / meta.chat_id
                await self._process_character_api(
                    raw, char_dir, cover_path, wash_images, wash_text, infer_json
                )
            except Exception as exc:
                print(f"[error] {raw.name} ({raw.chat_id}): {exc}")
                import traceback
                traceback.print_exc()
                continue

    async def _process_character_api(
        self,
        raw: RawCharacter,
        char_dir: Path,
        cover_path: Optional[Path],
        wash_images: bool,
        wash_text: bool,
        infer_json: bool,
    ) -> None:
        """Process a character through API-only steps (no browser needed)."""
        # Download all character images from main_character_images
        await self._download_character_images(raw, char_dir)

        washed_cover_path: Optional[Path] = None
        if wash_images and cover_path:
            washed_cover = char_dir / "cover_image_washed.jpg"
            if self.config.mule_router.api_key:
                wash_prompt = None
                try:
                    llm = LLMClient(self.config)
                    wash_prompt = await llm.generate_image_prompt(raw.name, raw.backstory)
                    print(f"    [img-prompt] {wash_prompt[:100]}...")
                except Exception as exc:
                    print(f"    [img-prompt error] {exc}, using default prompt")
                washer = ImageWasher(self.config.mule_router)
                washed_cover_path = await washer.wash(cover_path, washed_cover, prompt=wash_prompt)
            else:
                washed_cover_path = await placeholder_wash(cover_path, washed_cover)
            print(f"[wash image] {washed_cover_path.name}")

        washed_text: Optional[WashedCharacter] = None
        if wash_text:
            llm = LLMClient(self.config)
            new_name = await llm.generate_name(raw.name, raw.backstory)
            new_backstory, new_opening = await llm.wash_text(
                raw.name, new_name, raw.backstory, raw.opening
            )
            washed_text = WashedCharacter(
                chat_id=raw.chat_id,
                original_name=raw.name,
                new_name=new_name,
                backstory=new_backstory,
                opening=new_opening,
                tags=raw.tags,
                cover_path=washed_cover_path or cover_path,
            )
            (char_dir / "washed.json").write_text(
                washed_text.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"[wash text] {raw.name} -> {new_name}")

        if infer_json:
            if not washed_text:
                washed_text = WashedCharacter(
                    chat_id=raw.chat_id,
                    original_name=raw.name,
                    new_name=raw.name,
                    backstory=raw.backstory,
                    opening=raw.opening,
                    tags=raw.tags,
                    cover_path=washed_cover_path or cover_path,
                )
            llm = LLMClient(self.config)
            image_name = (washed_cover_path or cover_path or Path("cover_image.jpg")).name
            card_data = await llm.infer_card(washed_text, image_name)
            card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": card_data}
            (char_dir / "character.json").write_text(
                json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"[infer json] {char_dir / 'character.json'}")

    async def _download_character_images(
        self, raw: RawCharacter, char_dir: Path
    ) -> None:
        """Download all unique images from main_character_images."""
        urls = list(dict.fromkeys(raw.main_character_images))  # dedupe, keep order
        if not urls:
            return

        images_dir = char_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        def _sync_download() -> int:
            import httpx as _httpx
            count = 0
            with _httpx.Client(timeout=60, trust_env=False, follow_redirects=True) as client:
                for i, url in enumerate(urls, 1):
                    # Extract filename from URL path
                    fname = url.rstrip("/").split("/")[-1].split("?")[0]
                    if not fname or "." not in fname:
                        fname = f"image_{i}.jpg"
                    dest = images_dir / fname
                    if dest.exists():
                        count += 1
                        continue
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                        dest.write_bytes(resp.content)
                        count += 1
                    except Exception as exc:
                        print(f"    [img error] {fname}: {exc}")
            return count

        total = await asyncio.to_thread(_sync_download)
        print(f"[images] {total}/{len(urls)} downloaded -> {images_dir.name}/")

    async def run_chat_scrape(
        self,
        chat_urls: list[str],
        infer_from_chat: bool = False,
        wash_images: bool = False,
        wash_text: bool = False,
    ) -> None:
        """Scrape chat pages URLs and output MD files for LLM reverse engineering."""
        async with TipsyScraper(
            headless=self.config.crawler.headless,
            use_stealth=self.config.crawler.use_stealth,
            request_delay_ms=self.config.crawler.request_delay_ms,
        ) as scraper:
            for url in chat_urls:
                try:
                    await self._process_chat_url(scraper, url, infer_from_chat, wash_images, wash_text)
                except Exception as exc:
                    print(f"[error] {url}: {exc}")
                    import traceback
                    traceback.print_exc()
                    continue
                await asyncio.sleep(self.config.crawler.request_delay_ms / 1000)

    async def _process_chat_url(
        self,
        scraper: TipsyScraper,
        chat_url: str,
        infer_from_chat: bool,
        wash_images: bool,
        wash_text: bool,
    ) -> None:
        """Process a single chat URL: scrape → MD → optionally infer JSON."""
        print(f"[scrape chat] {chat_url}")
        record = await scraper.scrape_chat_page(chat_url)

        # Create output directory
        char_dir = self.output_dir / "chat_records" / record.chat_id
        char_dir.mkdir(parents=True, exist_ok=True)

        # Write MD file with character messages only
        md_path = char_dir / f"{record.character_name.replace(' ', '_')}_messages.md"
        md_content = f"# {record.character_name}\n\n"
        for i, msg in enumerate(record.messages, 1):
            md_content += f"## Message {i}\n\n{msg}\n\n---\n\n"
        md_path.write_text(md_content, encoding="utf-8")
        print(f"[md] {md_path.name} ({len(record.messages)} messages)")

        # Optionally run LLM reverse engineering
        if infer_from_chat:
            llm = LLMClient(self.config)
            print(f"[infer from chat] {record.character_name}")
            card_data = await llm.infer_from_chat(record.character_name, record.messages)
            card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": card_data}
            json_path = char_dir / "character.json"
            json_path.write_text(
                json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"[json] {json_path}")

        # Optionally wash text (if also provided with public page data)
        if wash_text:
            print(f"[wash text] skipped - chat mode only outputs raw messages")

        # Optionally wash images (not applicable in chat mode without cover URL)
        if wash_images:
            print(f"[wash image] skipped - chat mode does not include cover images")
