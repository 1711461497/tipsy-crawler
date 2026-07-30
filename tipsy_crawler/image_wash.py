"""MuleRouter async image editing wrapper for qwen-image-edit-spicy."""

import asyncio
import base64
import io
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import MuleRouterConfig

# Max dimension for images sent to MuleRouter (avoid VALIDATION_ERROR on large files)
_MAX_DIMENSION = 1024
_MAX_FILE_BYTES = 4 * 1024 * 1024  # 4 MB after encoding


def _preprocess_image(image_path: Path) -> Path:
    """Convert GIF/animated to first-frame PNG and resize if too large.

    Returns the path to a ready-to-encode PNG (may be the original if no
    conversion needed). Temporary files are placed in the system temp dir.
    """
    from PIL import Image

    suffix = image_path.suffix.lower()
    needs_convert = suffix in (".gif", ".webp", ".bmp", ".tiff")
    img = Image.open(image_path)

    # For animated formats, take the first frame
    if suffix == ".gif":
        img.seek(0)

    # Convert to RGB (drops alpha, palette, etc.)
    img = img.convert("RGB")

    # Resize if any dimension exceeds max
    w, h = img.size
    if max(w, h) > _MAX_DIMENSION:
        ratio = _MAX_DIMENSION / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        needs_convert = True

    if needs_convert:
        tmp = Path(tempfile.mktemp(suffix=".png", prefix=f"wash_{image_path.stem}_"))
        img.save(tmp, "PNG", optimize=True)
        # If still too large, reduce quality via JPEG
        if tmp.stat().st_size > _MAX_FILE_BYTES:
            tmp2 = tmp.with_suffix(".jpg")
            img.save(tmp2, "JPEG", quality=85, optimize=True)
            tmp.unlink(missing_ok=True)
            return tmp2
        return tmp

    return image_path


class ImageWasher:
    """Wash character cover images via MuleRouter image models."""

    def __init__(self, config: MuleRouterConfig):
        self.config = config

    def _vendor(self) -> str:
        """Detect vendor from model name."""
        model = self.config.image_model.lower()
        if "spicy" in model:
            return "carrothub"
        if "gpt-image" in model:
            return "openai"
        return "alibaba"

    def _route(self) -> str:
        """Route to vendor-specific endpoint with model name in path."""
        model = self.config.image_model
        vendor = self._vendor()
        # Only gpt-image models support the /edit endpoint;
        # carrothub/alibaba models always use /generation
        if "gpt-image" in model.lower():
            mode = self.config.image_edit_mode
        else:
            mode = "generation"
        return f"{self.config.base_url.rstrip('/')}/vendors/{vendor}/v1/{model}/{mode}"

    def _build_payload(self, b64_image: str, prompt: str, seed: Optional[int] = None) -> dict:
        model = self.config.image_model.lower()
        if "gpt-image" in model:
            # OpenAI gpt-image-2 edit format
            payload = {"image": b64_image, "prompt": prompt}
            if seed is not None:
                payload["seed"] = seed
            return payload
        if "spicy" in model:
            payload = {"image": b64_image, "prompt": prompt}
            if seed is not None:
                payload["seed"] = seed
            return payload
        # Generic alibaba-style payload
        payload = {"images": [b64_image], "prompt": prompt}
        if seed is not None:
            payload["seed"] = seed
        return payload

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def wash(
        self,
        image_path: Path,
        output_path: Path,
        prompt: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Path:
        """Submit image wash task, poll, and save result.

        Uses sync httpx in a worker thread to avoid event loop conflicts
        with Playwright (which can cause ConnectError on some systems).
        """
        prompt = prompt or (
            "Slightly adjust the character's hair and outfit color palette to a "
            "different but harmonious scheme. Keep pose, face, expression, and "
            "background unchanged."
        )

        # Preprocess: convert GIF → first frame PNG, resize if too large
        processed = _preprocess_image(image_path)
        print(f"    [preprocess] {image_path.name} -> {processed.name} ({processed.stat().st_size} bytes)")

        b64_image = base64.b64encode(processed.read_bytes()).decode("utf-8")
        # Clean up temp preprocessed file
        if processed != image_path:
            processed.unlink(missing_ok=True)
        # Use data URI prefix for reliable content-type detection
        if processed.suffix.lower() in (".jpg", ".jpeg"):
            b64_image = f"data:image/jpeg;base64,{b64_image}"
        else:
            b64_image = f"data:image/png;base64,{b64_image}"

        url = self._route()
        payload = self._build_payload(b64_image, prompt, seed)
        api_key = self.config.api_key
        poll_interval = self.config.poll_interval
        max_poll_time = self.config.max_poll_time

        def _sync_wash() -> Path:
            """Run the entire network flow (submit → poll → download) in sync httpx."""
            with httpx.Client(timeout=120, trust_env=False) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                task_data = resp.json()
                task_id = (
                    task_data.get("task_id")
                    or task_data.get("id")
                    or (task_data.get("task_info", {}) or {}).get("id")
                )
                if not task_id:
                    raise RuntimeError(f"No task_id in response: {task_data}")
                print(f"    [task] id={task_id}")

                result = self._poll_task_sync(client, task_id, api_key, poll_interval, max_poll_time)

                # MuleRouter returns {"images": ["url1", ...]} at top level
                images = result.get("images", [])
                image_url = images[0] if images else None
                # Fallback: check other possible locations
                if not image_url:
                    image_url = (
                        result.get("output", {}).get("url")
                        or result.get("image_url")
                        or (result.get("task_info", {}) or {}).get("output", {}).get("url")
                    )
                if not image_url:
                    raise RuntimeError(f"No image URL in task result: {result}")
                print(f"    [result] {image_url[:120]}...")

                img_resp = client.get(image_url)
                img_resp.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_resp.content)
                return output_path

        return await asyncio.to_thread(_sync_wash)

    def _poll_task_sync(
        self, client: httpx.Client, task_id: str, api_key: str,
        poll_interval: int, max_poll_time: int,
    ) -> dict:
        """Poll MuleRouter until task completes or times out (sync version)."""
        model = self.config.image_model
        vendor = self._vendor()
        mode = self.config.image_edit_mode if "gpt-image" in model.lower() else "generation"
        status_url = f"{self.config.base_url.rstrip('/')}/vendors/{vendor}/v1/{model}/{mode}/{task_id}"
        deadline = time.time() + max_poll_time
        while time.time() < deadline:
            resp = client.get(
                status_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            status = (
                data.get("status")
                or (data.get("task_info", {}) or {}).get("status")
                or ""
            ).lower()
            if status in ("succeeded", "completed", "success"):
                return data
            if status in ("failed", "error"):
                detail = (data.get("task_info", {}) or {}).get("error") or data.get("error", data)
                raise RuntimeError(f"Image wash failed: {detail}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Image wash polling timed out for task {task_id}")


async def placeholder_wash(
    image_path: Path, output_path: Path, prompt: Optional[str] = None
) -> Path:
    """Copy the original image when no API key is configured (MVP fallback)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_path.read_bytes())
    return output_path
