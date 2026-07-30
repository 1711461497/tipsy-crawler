"""Playwright-based scraping for Tipsy.chat."""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import AuthorInfo, CharacterMeta, ChatRecord, RawCharacter


PROFILE_GRID_SELECTOR = ".grid.gap-3\\.5"
CARD_SELECTOR = ".grid.gap-3\\.5 > div"
CARD_TITLE_SELECTOR = "span.truncate"
CARD_LINK_SELECTOR = "a[href^='/chat/']"
CARD_IMAGE_SELECTOR = "img"


def _extract_chat_id(href: str) -> Optional[str]:
    """Extract chat_id from a public character link href."""
    match = re.search(r"/chat/(\d+)/public", href)
    return match.group(1) if match else None


class TipsyScraper:
    """Scraper for Tipsy.chat author profiles and character public pages."""

    def __init__(
        self,
        headless: bool = True,
        use_stealth: bool = True,
        proxy: Optional[str] = None,
        request_delay_ms: int = 1000,
    ):
        self.headless = headless
        self.use_stealth = use_stealth
        self.proxy = proxy
        self.request_delay_ms = request_delay_ms
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "TipsyScraper":
        self._playwright = await async_playwright().start()
        browser_kwargs = {"headless": self.headless}
        if self.proxy:
            browser_kwargs["proxy"] = {"server": self.proxy}

        # Fallback to system Chrome if Playwright's bundled Chromium isn't downloaded
        try:
            self._browser = await self._playwright.chromium.launch(**browser_kwargs)
        except Exception:
            system_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if system_chrome.exists():
                browser_kwargs["executable_path"] = str(system_chrome)
                self._browser = await self._playwright.chromium.launch(**browser_kwargs)
            else:
                raise
        context_kwargs = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        }
        self._context = await self._browser.new_context(**context_kwargs)
        if self.use_stealth:
            await self._context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                """
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Scraper not entered")
        return self._context.new_page()

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        """Strip Cloudflare cdn-cgi transforms to get the raw image path."""
        import re
        return re.sub(r"/cdn-cgi/image/[^/]+/", "/", url)

    async def download_with_browser(self, url: str, dest: Path) -> Path:
        """Download a URL using a fresh page to resolve Cloudflare challenges."""
        # Try raw URL first (strip cdn-cgi transforms)
        raw_url = self._normalize_image_url(url)
        page = await self._new_page()
        try:
            # Navigate to image URL; Cloudflare may show a challenge page first
            await page.goto(raw_url, wait_until="load", timeout=60000)
            # Wait up to 15s for Cloudflare challenge to resolve
            for _ in range(15):
                title = await page.title()
                if "Just a moment" not in title:
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError(f"Cloudflare challenge did not resolve for {url}")

            # Try fetching via browser request API
            response = await page.context.request.get(raw_url)
            if response.status >= 400:
                # Fallback: try reading image bytes from the loaded page if it's an image
                try:
                    b64 = await page.evaluate(
                        """async () => {
                            const resp = await fetch(window.location.href);
                            const blob = await resp.blob();
                            return new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result.split(',')[1]);
                                reader.readAsDataURL(blob);
                            });
                        }"""
                    )
                    import base64
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(base64.b64decode(b64))
                    return dest
                except Exception:
                    raise RuntimeError(f"Browser download failed: {response.status} for {url}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await response.body())
            return dest
        finally:
            await page.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def scan_author(self, profile_url: str) -> tuple[AuthorInfo, list[CharacterMeta]]:
        """Scan an author profile and return all character cards."""
        page = await self._new_page()
        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector(PROFILE_GRID_SELECTOR, timeout=60000)
            # Give React a moment to settle
            await asyncio.sleep(1.0)
            html = await page.content()
        finally:
            await page.close()

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(CARD_SELECTOR)

        author_uid = self._extract_author_uid(profile_url)
        results: list[CharacterMeta] = []
        for card in cards:
            title_el = card.select_one(CARD_TITLE_SELECTOR)
            link_el = card.select_one(CARD_LINK_SELECTOR)
            img_el = card.select_one(CARD_IMAGE_SELECTOR)
            if not (title_el and link_el and img_el):
                continue
            chat_id = _extract_chat_id(link_el.get("href", ""))
            if not chat_id:
                continue
            results.append(
                CharacterMeta(
                    name=title_el.get_text(strip=True),
                    chat_id=chat_id,
                    cover_url=img_el.get("src", ""),
                    profile_url=profile_url,
                    author_uid=author_uid,
                )
            )

        info = AuthorInfo(
            uid=author_uid,
            url=profile_url,
            character_count=len(results),
            scraped_at=datetime.utcnow(),
        )
        return info, results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch_character(self, chat_id: str) -> RawCharacter:
        """Fetch raw text and image URLs from a character public page."""
        url = f"https://tipsy.chat/chat/{chat_id}/public"
        page = await self._new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector("body", timeout=30000)
            # Wait up to 10s for BACKSTORY; if absent, still parse what we got
            try:
                await page.wait_for_selector("text=BACKSTORY", timeout=10000)
            except Exception:
                pass
            title = await page.title()
            html = await page.content()
        finally:
            await page.close()

        return self._parse_character_page(chat_id, url, title, html)

    def _parse_character_page(
        self, chat_id: str, url: str, title: str, html: str
    ) -> RawCharacter:
        """Parse the character public page HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # Title usually contains "Public Memories of {Name} | ..."
        name = title.split("|")[0].replace("Public Memories of", "").strip()

        # Find first message bubble containing both BACKSTORY and OPENING
        body_text = soup.get_text("\n", strip=True)
        backstory, opening, tags, main_images, lang = self._split_memories(body_text)

        # Fallback: if no structured memories found, try extracting chat messages
        if not backstory and not opening:
            # Check if page has "No Memory" (nothing to extract)
            if "no memory" in body_text.lower()[:500]:
                pass  # Leave empty
            else:
                char_msgs, user_msgs = self._extract_chat_messages(body_text, name)
                if char_msgs:
                    # Use character messages as backstory + opening
                    backstory = "\n\n".join(char_msgs)
                    opening = char_msgs[0] if char_msgs else ""
                    lang = "chat"
                    print(f"    [chat-fallback] extracted {len(char_msgs)} char messages, {len(user_msgs)} user messages")

        # Also collect markdown image URLs from MAIN CHARACTER section
        main_images = self._extract_main_character_images(html) or main_images

        return RawCharacter(
            chat_id=chat_id,
            name=name,
            title=title,
            backstory=backstory,
            opening=opening,
            tags=tags,
            main_character_images=main_images,
            cover_url="",
            source_url=url,
            language=lang,
        )

    def _split_memories(
        self, text: str
    ) -> tuple[str, str, list[str], list[str], str]:
        """Split raw page text into backstory, opening, tags, and images."""
        # Try English first
        for marker_backstory, marker_opening, marker_main, marker_tags, lang in [
            ("BACKSTORY", "OPENING", "MAIN CHARACTER", "TAGS:", "en"),
            ("ANTECEDENTES", "APERTURA", "PERSONAJE PRINCIPAL", "TAGS:", "es"),
            ("НАЧАЛО", "ПРЕДЫСТОРИЯ", "ГЛАВНЫЙ ГЕРОЙ", "TAGS:", "ru"),
        ]:
            try:
                result = self._extract_sections(
                    text, marker_backstory, marker_opening, marker_main, marker_tags
                )
                if result[0] and result[1]:
                    return (*result, lang)
            except ValueError:
                continue

        # Fallback: take everything between first BACKSTORY-like and next ---
        return "", "", [], [], "unknown"

    def _extract_sections(
        self,
        text: str,
        backstory_marker: str,
        opening_marker: str,
        main_marker: str,
        tags_marker: str,
    ) -> tuple[str, str, list[str], list[str]]:
        """Extract sections between known markers."""
        idx_back = text.index(backstory_marker)
        idx_open = text.index(opening_marker)
        # MAIN CHARACTER is optional
        idx_main = text.find(main_marker, idx_open)
        idx_tags = text.find(tags_marker, idx_main if idx_main != -1 else idx_open)

        backstory = text[idx_back + len(backstory_marker) : idx_open].strip()
        backstory = self._clean_markdown_links(backstory)

        end_opening = idx_main if idx_main != -1 else idx_tags
        if end_opening == -1:
            # Use the next "- - -" after opening as fallback
            dash_idx = text.find("- - -", idx_open + len(opening_marker))
            end_opening = dash_idx if dash_idx != -1 else len(text)
        opening = text[idx_open + len(opening_marker) : end_opening].strip()
        opening = self._clean_markdown_links(opening)

        tags: list[str] = []
        main_images: list[str] = []

        if idx_main != -1:
            end_main = idx_tags if idx_tags != -1 else text.find("- - -", idx_main)
            if end_main == -1:
                end_main = len(text)
            main_section = text[idx_main : end_main]
            main_images = re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", main_section)

        if idx_tags != -1:
            tag_section = text[idx_tags + len(tags_marker) : idx_tags + 500]
            # Tags are usually italicized; stop at the closing '*' or newline
            tag_section = tag_section.split("\n")[0]
            if "*" in tag_section:
                tag_section = tag_section[: tag_section.index("*")]
            tags = [t.strip().strip("*").strip() for t in tag_section.split("|") if t.strip()]

        return backstory, opening, tags, main_images

    @staticmethod
    def _extract_chat_messages(text: str, char_name: str) -> tuple[list[str], list[str]]:
        """Extract character and user messages from chat page text.

        Chat pages have messages in the format:
            Username:
            message text...
            ---
            CharacterName:
            response text...

        Returns (char_messages, user_messages).
        """
        lines = text.split("\n")
        messages: list[tuple[str, str]] = []  # (sender_type, content)

        # Footer/nav patterns to stop at
        stop_patterns = [
            "Supported Cards", "Privacy Policy", "Terms of Service",
            "Subscription FAQ", "Community Guidelines", "Beginner's Guide",
            "About Us", "Blog", "© 20", "All rights reserved",
            "All responses are AI-generated", "Your chats and accounts",
        ]

        # Normalize character name for matching (strip special unicode chars)
        char_name_clean = re.sub(r'[^\w\s]', '', char_name).lower().strip()

        current_sender = None
        current_lines: list[str] = []
        sender_type = None  # "char" or "user"

        def flush():
            nonlocal current_lines, current_sender, sender_type
            content = "\n".join(current_lines).strip()
            if content and sender_type:
                messages.append((sender_type, content))
            current_lines = []
            current_sender = None
            sender_type = None

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Check for stop patterns
            if any(p in line for p in stop_patterns):
                flush()
                break

            # Skip empty lines (but preserve within messages)
            if not line:
                if current_sender is not None:
                    current_lines.append("")
                i += 1
                continue

            # Check for "---" separator (message boundary)
            if line in ("---", "- - -"):
                flush()
                i += 1
                continue

            # Check if this line is a sender header: "Username:" or "Username | Subtitle:"
            # Pattern: line ends with ":" and next non-empty line is content
            header_match = re.match(r'^(.+?):\s*$', line)
            if header_match:
                sender_name = header_match.group(1).strip()
                sender_clean = re.sub(r'[^\w\s]', '', sender_name).lower().strip()

                # Determine if this is the character or a user
                is_char = (
                    char_name_clean and char_name_clean in sender_clean
                ) or (
                    sender_clean and sender_clean in char_name_clean
                )

                flush()
                current_sender = sender_name
                sender_type = "char" if is_char else "user"
                i += 1
                continue

            # Regular content line
            if current_sender is not None:
                current_lines.append(line)
            i += 1

        flush()

        char_msgs = [m[1] for m in messages if m[0] == "char"]
        user_msgs = [m[1] for m in messages if m[0] == "user"]
        return char_msgs, user_msgs

    @staticmethod
    def _clean_markdown_links(text: str) -> str:
        """Remove markdown image syntax from text but keep plain URLs readable."""
        return re.sub(r"!\[(.*?)\]\((https?://[^\s)]+)\)", r"\1: \2", text)

    @staticmethod
    def _extract_main_character_images(html: str) -> list[str]:
        """Extract image URLs from markdown in MAIN CHARACTER section."""
        return re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", html)

    @staticmethod
    def _extract_author_uid(profile_url: str) -> str:
        """Extract author UID from profile URL."""
        match = re.search(r"/profile/(\d+)", profile_url)
        return match.group(1) if match else "unknown"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def scrape_chat_page(self, chat_url: str) -> ChatRecord:
        """Scrape a chat page and extract character messages only."""
        # Extract chat_id from URL
        match = re.search(r"/chat/(\d+)", chat_url)
        if not match:
            raise ValueError(f"Invalid chat URL: {chat_url}")
        chat_id = match.group(1)

        page = await self._new_page()
        try:
            await page.goto(chat_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector("body", timeout=30000)
            # Wait for content to load
            await asyncio.sleep(2)
            title = await page.title()
            text = await page.evaluate("document.body.innerText")
        finally:
            await page.close()

        # Extract character name from title
        name = title.split("|")[0].replace("Chat With", "").strip()

        # Extract character messages (the main narrative content)
        # The page contains the character's opening/greeting message
        # We'll extract the main content blocks
        messages = self._extract_char_messages(text, name)

        return ChatRecord(
            chat_id=chat_id,
            character_name=name,
            messages=messages,
        )

    @staticmethod
    def _extract_char_messages(text: str, char_name: str) -> list[str]:
        """Extract character messages from chat page text."""
        # Split into lines and filter out navigation/footer content
        lines = text.split("\n")
        messages = []
        current_msg = []
        in_message = False

        # Skip common footer/navigation patterns
        skip_patterns = [
            "Top Pick", "Pinned", "Supported Cards", "Privacy Policy",
            "Terms of Service", "Subscription FAQ", "Community Guidelines",
            "Beginner's Guide", "About Us", "Blog", "© 20", "All rights reserved",
            "Download", "Create", "CID:", "Hide Profile", "Auto",
            "All responses are AI-generated", "Your chats and accounts are encrypted",
        ]

        for line in lines:
            line = line.strip()
            if not line:
                if current_msg:
                    current_msg.append("")
                continue

            # Skip footer/navigation lines
            if any(pattern in line for pattern in skip_patterns):
                if current_msg:
                    messages.append("\n".join(current_msg).strip())
                    current_msg = []
                in_message = False
                continue

            # Start collecting message content
            if not in_message and line:
                in_message = True
            if in_message:
                current_msg.append(line)

        # Add the last message if any
        if current_msg:
            messages.append("\n".join(current_msg).strip())

        # If we got multiple blocks, merge them into one coherent message
        # (since this is typically one long opening message)
        if messages:
            # Join all message blocks
            full_message = "\n\n".join(msg for msg in messages if msg)
            return [full_message] if full_message else []

        return []
