"""CLI entry point for the Tipsy crawler."""

import argparse
import asyncio
from pathlib import Path

from .config import load_config
from .pipeline import CrawlPipeline


AUTHOR_URLS = [
    "https://tipsy.chat/profile/1755409757272128854?tab=Characters",
    "https://tipsy.chat/profile/1760269160251868725?tab=Characters",
    "https://tipsy.chat/profile/1771562293101002310?tab=Characters",
    "https://tipsy.chat/profile/1773519775473701771?tab=Characters",
    "https://tipsy.chat/profile/1761090629191586613?tab=Characters",
    "https://tipsy.chat/profile/1755149625225551379?tab=Characters",
    "https://tipsy.chat/profile/1755043218552811749?tab=Characters",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Tipsy.chat character card crawler")
    parser.add_argument("--config", "-c", type=Path, help="Path to config.yaml")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("/Users/akb/Documents/AKB_file/内容/character_asset/Tipsy角色卡洗卡测试"),
        help="Output directory",
    )
    parser.add_argument("--max-chars", "-n", type=int, default=3, help="Characters to process")
    parser.add_argument(
        "--authors",
        "-a",
        nargs="+",
        help="Override author profile URLs",
    )
    parser.add_argument(
        "--char-urls",
        nargs="+",
        help="Character page URLs to process through the full pipeline",
    )
    parser.add_argument(
        "--chat-urls",
        nargs="+",
        help="Chat page URLs to scrape (outputs MD files for LLM reverse engineering)",
    )
    parser.add_argument(
        "--infer-from-chat",
        action="store_true",
        help="After scraping chat MD, run LLM reverse engineering to produce JSON",
    )
    parser.add_argument(
        "--wash-images",
        action="store_true",
        help="Run image washing (requires MuleRouter API key)",
    )
    parser.add_argument(
        "--wash-text",
        action="store_true",
        help="Run text washing (requires LLM API key)",
    )
    parser.add_argument(
        "--infer-json",
        action="store_true",
        help="Run JSON inference (requires LLM API key)",
    )
    parser.add_argument(
        "--image-model",
        type=str,
        default=None,
        help="Override image wash model (e.g. gpt-image-2, qwen-image-edit-spicy)",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run browser headless",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    config.crawler.output_dir = args.output
    config.crawler.headless = args.headless
    if args.image_model:
        config.mule_router.image_model = args.image_model

    pipeline = CrawlPipeline(config)

    if args.char_urls:
        # Direct character URL mode — full pipeline
        asyncio.run(
            pipeline.run_char_urls(
                char_urls=args.char_urls,
                wash_images=args.wash_images,
                wash_text=args.wash_text,
                infer_json=args.infer_json,
            )
        )
    elif args.chat_urls:
        # Chat scraping mode
        asyncio.run(
            pipeline.run_chat_scrape(
                chat_urls=args.chat_urls,
                infer_from_chat=args.infer_from_chat,
                wash_images=args.wash_images,
                wash_text=args.wash_text,
            )
        )
    else:
        # Author scan mode
        urls = args.authors or AUTHOR_URLS[:1]
        asyncio.run(
            pipeline.run_mvp(
                author_urls=urls,
                max_chars=args.max_chars,
                wash_images=args.wash_images,
                wash_text=args.wash_text,
                infer_json=args.infer_json,
            )
        )


if __name__ == "__main__":
    main()
