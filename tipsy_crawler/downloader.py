"""Async image downloader with retry and content-type detection."""

import asyncio
from pathlib import Path
from typing import Optional

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://tipsy.chat/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def download_image(
    url: str,
    dest: Path,
    session: Optional[aiohttp.ClientSession] = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> Path:
    """Download an image to the destination path, inferring extension from content type."""
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = user_agent
    close_session = session is None
    session = session or aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=60),
    )
    try:
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            data = await resp.read()
            content_type = resp.headers.get("Content-Type", "").lower()
    finally:
        if close_session:
            await session.close()

    ext = _ext_from_content_type(content_type) or _ext_from_url(url) or ".jpg"
    dest = dest.with_suffix(ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _ext_from_content_type(content_type: str) -> Optional[str]:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    for mime, ext in mapping.items():
        if mime in content_type:
            return ext
    return None


def _ext_from_url(url: str) -> Optional[str]:
    suffix = Path(url.split("?")[0]).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else None


async def download_images(
    urls: list[tuple[str, Path]],
    delay_ms: int = 500,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[Path]:
    """Download multiple images with a small delay between starts."""
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = user_agent
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as session:
        results: list[Path] = []
        for url, dest in urls:
            try:
                path = await download_image(url, dest, session=session)
                results.append(path)
            except Exception as exc:
                results.append(Path("ERROR") / str(exc))
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
        return results
